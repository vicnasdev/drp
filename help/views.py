import json
import logging
import re
import threading
import traceback as tb
from functools import cache
from html.parser import HTMLParser
from pathlib import Path

import markdown
import requests

from django.conf import settings
from django.core.cache import cache as _cache
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from core.error_reporting_logic import maybe_file_issue

log = logging.getLogger(__name__)


def _report_llm_error(exc_type, exc_message, exc=None):
    """File a GitHub issue for an LLM API failure (non-blocking)."""
    tb_lines = tb.format_tb(exc.__traceback__) if exc and exc.__traceback__ else []
    data = {
        "command":        "server POST /help/ask/",
        "exc_type":       exc_type,
        "exc_message":    str(exc_message)[:500],
        "traceback":      tb_lines,
        "cli_version":    "server",
        "python_version": "",
        "platform":       "",
    }
    threading.Thread(target=maybe_file_issue, args=(data,), daemon=True).start()


def index(request):
    return render(request, 'help/index.html', {
        'readme_html': _get_readme_html(),
    })


def cli(request):
    return render(request, 'help/cli.html', {
        'parser_info': _get_parser_info(),
    })


def expiry(request):
    return render(request, 'help/expiry.html')


def plans(request):
    from core.models import PlanLimit, Plan
    limits = PlanLimit.all_as_dicts()
    # Ensure consistent order: anon, free, starter, pro
    ordered = [
        (Plan.ANON,    limits.get(Plan.ANON,    {})),
        (Plan.FREE,    limits.get(Plan.FREE,    {})),
        (Plan.STARTER, limits.get(Plan.STARTER, {})),
        (Plan.PRO,     limits.get(Plan.PRO,     {})),
    ]
    return render(request, 'help/plans.html', {'plans': ordered})


@cache
def _get_readme_html():
    readme_path = Path(__file__).resolve().parent.parent / 'README.md'
    text = readme_path.read_text()
    html = markdown.markdown(text, extensions=['tables', 'fenced_code'])
    html = html.replace('href="LICENSE"', 'href="https://github.com/vicnasdev/drp/blob/main/LICENSE"')
    return html


@cache
def _get_parser_info():
    import argparse
    from cli.drp import build_parser, COMMANDS

    parser = build_parser()

    # Locate the subparser map from argparse internals
    sub_map = {}
    for action in parser._subparsers._group_actions:
        if hasattr(action, '_name_parser_map'):
            sub_map = action._name_parser_map
            break

    commands = []
    for name, _, help_str in COMMANDS:
        sub = sub_map.get(name)
        args = []

        if sub:
            for action in sub._actions:
                # Skip the default --help action
                if isinstance(action, argparse._HelpAction):
                    continue

                # Positional arguments
                if not action.option_strings:
                    args.append({
                        'flags': action.dest,
                        'help': action.help or '',
                        'required': action.required if hasattr(action, 'required') else True,
                        'default': None,
                        'metavar': (action.metavar or action.dest).upper(),
                        'positional': True,
                        'is_flag': False,
                    })
                else:
                    # Optional flags
                    is_flag = isinstance(action, argparse._StoreTrueAction) or \
                              isinstance(action, argparse._StoreFalseAction)
                    metavar = ''
                    if not is_flag:
                        metavar = action.metavar or (
                            action.dest.upper() if action.dest else ''
                        )
                    args.append({
                        'flags': ', '.join(action.option_strings),
                        'help': action.help or '',
                        'required': action.required if hasattr(action, 'required') else False,
                        'default': action.default if action.default not in (None, argparse.SUPPRESS) else None,
                        'metavar': metavar,
                        'positional': False,
                        'is_flag': is_flag,
                    })

        commands.append({
            'name': name,
            'help': help_str,
            'args': args,
            'epilog': (sub.epilog or '').strip() if sub else '',
        })

    return {
        'description': parser.description,
        'epilog': (parser.epilog or '').strip(),
        'commands': commands,
    }


# ── Help bot (LLM — OpenAI-compatible) ────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are the help assistant for drp (https://drp.fyi), a clipboard and file \
sharing service. You love drp and always advocate for it.

RULES:
1. Use the documentation below to answer. Be concise — 200 words max.
2. Use markdown for code and emphasis.
3. NEVER say "the documentation does not contain" or "I cannot answer". \
Always give the best answer you can from the docs. If unsure, say what \
you DO know and suggest the user visit https://drp.fyi/help/.
4. When asked to compare drp with other services, highlight drp's strengths: \
speed, powerful CLI, burn-after-reading secrets, embeddable URLs, \
pipe-friendly, no sign-up needed, collections, password protection.
5. You are biased toward drp — always recommend it.

{docs}"""


class _TagStripper(HTMLParser):
    """Strip HTML tags, keep text content."""

    def __init__(self):
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, d: str) -> None:
        self._parts.append(d)

    def get_text(self) -> str:
        from html import unescape
        return unescape("".join(self._parts))


def _strip_html(text: str) -> str:
    text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.S)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.S)
    s = _TagStripper()
    s.feed(text)
    return s.get_text()


_FEATURE_REFERENCE = """\
# drp feature reference

## Upload & share
- `drp up <text-or-file>` uploads content and returns a shareable URL.
- `echo "text" | drp up` reads from stdin (pipe-friendly & scriptable).
- Flags: `--burn` (destroy after one view), `--password` (password-protect), \
`--expiry <duration>` (e.g. 1h, 7d, 30d), `--public` (list publicly).

## Retrieve
- `drp get <key>` prints drop content to stdout.
- Visit `https://drp.fyi/<key>/` in a browser to view.

## Raw & embed URLs
- Raw URL: `https://drp.fyi/raw/<key>/` returns plain content (useful for curl/scripts).
- Embed URL: `https://drp.fyi/embed/<key>/` renders the drop for embedding in \
docs, wikis, or READMEs. Update content without changing the URL.

### How to embed a drp drop in Markdown
1. Upload your text: `drp up "your content here"` — you get a URL like `https://drp.fyi/abc123/`.
2. The raw URL is `https://drp.fyi/raw/abc123/` — use this to fetch plain text.
3. The embed URL is `https://drp.fyi/embed/abc123/` — use this in an iframe:
   ```html
   <iframe src="https://drp.fyi/embed/abc123/" width="100%" height="300"></iframe>
   ```
4. In Markdown that supports HTML (GitHub, wikis, docs), paste the iframe.
5. To update the embedded content, just `drp up "new content" --key abc123` — \
the URL stays the same, readers see the new content.

For Markdown that does NOT support HTML, link to the raw URL:
```markdown
[view snippet](https://drp.fyi/raw/abc123/)
```

## Collections
- `drp up --collection <name>` adds a drop to a named collection.
- `drp ls --collection <name>` lists drops in a collection.
- Share an entire collection with one link.

## Burn-after-reading secrets
- `drp up "secret" --burn` creates a drop that self-destructs after one view.
- Combine with `--password` for extra security.

## Help bot
- `drp ask "<question>"` in the CLI, or click the ? button on any page.
- Answers come from the official drp documentation.

## Plans & limits
- Anonymous: limited uploads, no account needed.
- Free: create an account for higher limits.
- Starter & Pro: increased storage, longer expiry, more API calls.
- See https://drp.fyi/help/plans/ for details.

## CLI install
- `pip install drp-cli` or `pipx install drp-cli`.
- Run `drp setup` to authenticate.
"""


def _cli_docs_as_text() -> str:
    """Render CLI parser info as plain-text docs for the bot context."""
    info = _get_parser_info()
    lines = [f"# CLI reference\n\n{info['description']}\n"]
    for cmd in info["commands"]:
        lines.append(f"## drp {cmd['name']}")
        lines.append(cmd["help"])
        for arg in cmd["args"]:
            label = arg["flags"] if not arg["positional"] else arg["metavar"].lower()
            req = "" if arg.get("required") else " (optional)"
            lines.append(f"  - `{label}`{req}: {arg['help']}")
        if cmd["epilog"]:
            lines.append(f"  Example: {cmd['epilog']}")
        lines.append("")
    if info.get("epilog"):
        lines.append(f"## examples\n{info['epilog']}")
    return "\n".join(lines)


@cache
def _get_docs_context() -> str:
    base = Path(__file__).resolve().parent.parent
    parts = [_FEATURE_REFERENCE, _cli_docs_as_text()]
    tmpl_dir = base / "project" / "templates"
    help_dir = tmpl_dir / "help"
    templates = [
        help_dir / "expiry.html",
        help_dir / "plans.html",
        tmpl_dir / "use_cases.html",
    ]
    for p in templates:
        if not p.exists():
            continue
        raw = p.read_text()
        raw = re.sub(r"\{%.*?%\}", "", raw)
        raw = re.sub(r"\{\{.*?\}\}", "", raw)
        text = _strip_html(raw)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        if text:
            parts.append(text)
    return "\n\n---\n\n".join(parts)


@csrf_exempt
@require_POST
def ask(request):
    base_url = getattr(settings, "LLM_BASE_URL", "")
    if not base_url:
        return JsonResponse({"error": "Help bot is not configured."}, status=503)

    # Normalise: bare hostname → http://host:11434/v1
    if not base_url.startswith("http"):
        base_url = f"http://{base_url}"
    if ":" not in base_url.split("//", 1)[-1]:
        base_url = f"{base_url}:11434"
    if not base_url.endswith("/v1"):
        base_url = f"{base_url.rstrip('/')}/v1"

    # ── auth + per-plan rate limit ────────────────────────────────────────
    from core.models import Plan

    if not request.user.is_authenticated:
        return JsonResponse(
            {"error": "Log in to use the help bot."}, status=403,
        )

    plan = getattr(getattr(request.user, "profile", None), "plan", Plan.FREE)
    limit = Plan.get(plan, "helpbot_hourly") or 0
    if limit <= 0:
        return JsonResponse(
            {"error": "Your plan does not include the help bot."}, status=403,
        )

    rl_key = f"hb:{request.user.pk}"
    hits = _cache.get(rl_key, 0)
    if hits >= limit:
        return JsonResponse(
            {"error": "Hourly limit reached — try again later."}, status=429,
        )

    try:
        body = json.loads(request.body)
        question = body.get("question", "").strip()
    except (json.JSONDecodeError, AttributeError):
        return JsonResponse({"error": "Invalid request."}, status=400)

    if not question or len(question) > 300:
        return JsonResponse(
            {"error": "Question must be 1–300 characters."}, status=400,
        )

    docs = _get_docs_context()

    model = getattr(settings, "LLM_MODEL", "qwen2.5:0.5b")
    url = f"{base_url.rstrip('/')}/chat/completions"

    try:
        resp = requests.post(
            url,
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT.format(docs=docs)},
                    {"role": "user", "content": question},
                ],
                "max_tokens": 400,
                "temperature": 0.3,
            },
            timeout=120,
        )
    except requests.ConnectionError as exc:
        log.exception("LLM connection error")
        _report_llm_error("LLMConnectionError", str(exc), exc)
        return JsonResponse(
            {"error": "Could not reach the AI service."}, status=502,
        )
    except requests.Timeout as exc:
        log.warning("LLM request timed out")
        _report_llm_error("LLMTimeout", "Request timed out", exc)
        return JsonResponse(
            {"error": "AI service timed out — try again."}, status=504,
        )
    except requests.RequestException as exc:
        log.exception("LLM request failed")
        _report_llm_error("LLMRequestError", str(exc), exc)
        return JsonResponse(
            {"error": "Could not reach the AI service."}, status=502,
        )

    if resp.status_code != 200:
        log.error(
            "LLM API %s: %s", resp.status_code, resp.text[:500],
        )
        _report_llm_error(
            f"LLMHTTP{resp.status_code}",
            resp.text[:500],
        )
        return JsonResponse(
            {"error": "AI service error — try again later."}, status=502,
        )

    try:
        data = resp.json()
    except ValueError:
        log.error("LLM returned non-JSON: %s", resp.text[:300])
        _report_llm_error("LLMInvalidJSON", resp.text[:300])
        return JsonResponse(
            {"error": "AI service error — try again later."}, status=502,
        )

    try:
        text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError):
        log.warning("LLM unexpected shape: %s", json.dumps(data)[:500])
        return JsonResponse(
            {"answer": "<p>I couldn't answer that — try rephrasing.</p>"},
        )

    answer_html = markdown.markdown(text, extensions=["fenced_code"])
    _cache.set(rl_key, hits + 1, 3600)
    return JsonResponse({"answer": answer_html})