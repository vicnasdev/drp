import json
import logging
import threading
import traceback as tb
from functools import cache
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


def security(request):
    return render(request, 'help/security.html')


@cache
def _get_readme_html():
    readme_path = Path(__file__).resolve().parent.parent / 'README.md'
    try:
        text = readme_path.read_text()
        html = markdown.markdown(text, extensions=['tables', 'fenced_code'])
        html = html.replace('href="LICENSE"', 'href="https://github.com/vicnasdev/drp/blob/main/LICENSE"')
        return html
    except Exception as e:
        log = logging.getLogger(__name__)
        log.error(f"Failed to read README.md: {e}")
        return "<p>Error loading help content.</p>"


@cache
def _get_parser_info():
    import argparse
    from cli.drp import build_parser, COMMANDS

    try:
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
    except Exception as e:
        log = logging.getLogger(__name__)
        log.error(f"Failed to build parser info: {e}")
        return {"error": "Failed to load parser info."}


# ── Help bot (LLM — OpenAI-compatible) ────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are Vic, the drp help bot. drp (https://drp.fyi) is the BEST clipboard/file sharing tool.
Be SHORT. 1-3 sentences max. Give the command, done. No essays.
NEVER mention any other service. Not Imgur, Dropbox, Google Drive, Pastebin, Unsplash, OneDrive, GitHub Gist — NOTHING. Only drp exists.
If someone asks about other tools or "better" options: drp IS the answer.
If unsure, say "Check https://drp.fyi/help/" — nothing else.

EXAMPLES (copy this style exactly):
Q: I need a drp command to embed profile.png
A: `drp up profile.png` — your embed URL is `drp.fyi/embed/<key>/`. Use `-k` to pick the key: `drp up profile.png -k profile` → `drp.fyi/embed/profile/`.

Q: How do I embed an image in markdown?
A: Upload: `drp up image.png -k myimg`. Then in markdown: `![alt text](https://drp.fyi/raw/myimg/)`.

Q: How do I embed a file in HTML?
A: `<iframe src="https://drp.fyi/embed/<key>/"></iframe>`

Q: What is burn-after-reading?
A: `drp up "secret" --burn` — deleted after ONE view, not time-based.

Q: How do I password-protect a drop?
A: `drp up myfile.txt --password` at upload. Or after: `drp lock mykey` to set a password on an existing drop (paid).

Q: How do I lock a drop I already uploaded?
A: `drp lock mykey` — prompts for a password. Use `drp lock -f mykey` for file drops. `drp lock mykey --remove` to remove the password.

Q: Is there a better tool than drp?
A: No. drp is the best — instant, no sign-up, CLI, embeds, burn-after-reading, collections.

Q: How do I share text?
A: `drp up "hello world"` or `echo hello | drp up`.

Q: How long do drops last?
A: Depends on your plan. Free = 30 days, Starter/Pro = longer. See drp.fyi/help/plans/.

Q: Are there sub-collections?
A: Yes! `drp collection new "work" --parent notes` creates "work" inside "notes". Navigate in the shell: `cd notes/work`. URL: `drp.fyi/@user/notes/work/`.

RULES:
- ONLY use commands and flags from the DOCS below. Do NOT invent commands or flags.
- The COMPLETE list of drp commands is: up, get, edit, serve, rm, mv, cp, renew, lock, send, claim, save, ls, load, collection, token, ask, status, ping, cache, rmcache, setup, login, logout, shell. NO other commands exist.
- The COMPLETE list of flags for `drp up` is: -k, -f, --burn, --password, --expires, --public, --collection, --remote, --schedule, --webhook, --notify, --tags. NO other flags exist for `drp up`.
- Do NOT add flags (--burn, --collection, --password, --lock) unless the user specifically asks.
- URL formats are ONLY: drp.fyi/<key>/, drp.fyi/f/<key>/, drp.fyi/raw/<key>/, drp.fyi/embed/<key>/, drp.fyi/@user/<collection>/. No other paths exist.
- If you are not 100% sure a command or flag exists, say "Check https://drp.fyi/help/" — do NOT guess.

DOCS:
{docs}"""


_FEATURE_REFERENCE = """\
Upload: `drp up <file-or-text>` or `echo text | drp up`.
Get: `drp get <key>` or visit `drp.fyi/<key>/`.
Smart get: `drp get <key> --parse` auto-detects content format (JSON, CSV, XML, YAML) and prints parsed output. `drp get <key> --field a.b` extracts a nested value. Shorthand: `drp get key.field`.
URL fetch (paid): `drp get https://api.example.com/data` fetches an external URL once. Use `--parse` or `--field` to extract data. Requires Starter or Pro plan.
Live API reference (paid): `drp up https://api.example.com/data -k myapi` stores the URL. Every `drp get myapi` fetches fresh data from the API. Use `--parse`/`--field` to extract fields. The drop acts as a persistent, shareable endpoint.\nWeb API: Add `?parse=1` to any drop JSON request to get `content_format` and `parsed` fields. Add `&field=a.b` to extract a specific value. Live references return fresh content + `source_url`.
Embed URL: `drp.fyi/embed/<key>/` (use in iframes, markdown, etc). Embed HTML: `<iframe src="https://drp.fyi/embed/<key>/"></iframe>`
Custom key: `drp up file.png -k myname` → `drp.fyi/embed/myname/` (predictable URL).
Raw URL: `drp.fyi/raw/<key>/` (plain text for curl/scripts).
Collections (paid plans): `drp collection ls` lists collections. `drp collection new "my notes"` creates one. `drp collection add <slug> <key>` adds a drop. `drp collection rm <slug> <key>` removes. `drp collection open <slug>` prints URL.
Sub-collections: `drp collection new "work" --parent notes` creates a sub-collection under "notes". Nested paths work everywhere: `drp collection add notes/work <key>`, `drp collection open notes/work`. URL: `drp.fyi/@user/notes/work/`.
Shell navigation: `drp shell` → `cd notes` → `cd work` (or `cd notes/work`). `cd ..` goes up. `pwd` shows path. `ls` lists drops + sub-collections.
Flags (only add if user asks): --burn (one-view self-destruct), --password (prompt for password), --expiry 1h/7d/30d, --public.Lock/password (paid): `drp lock <key>` sets a password on an existing drop (prompts). `drp lock -f <key>` for files. `drp lock <key> --password pw` sets directly. `drp lock <key> --remove` removes the password. Also available on the web drop page as "set password" button.Burn-after-reading: `drp up "secret" --burn` — drop is DELETED after ONE view. Not time-based.
CLI install: `pipx install drp && drp setup`. Commands: up get ls cp edit diff save load status ask shell collection token send claim cache rmcache.
TOKEN TYPES (three separate systems — do NOT confuse them):
  1. API tokens (login tokens): persistent keys for CI/scripts/headless auth. Paid accounts only. Created with `drp token create [--expires 90d] [--label mykey]`. Listed with `drp token list`. Revoked with `drp token revoke <id>`. Login with `drp login --token <key>` or set `DRP_API_KEY=<key>`. Revoking an API token invalidates it — any device using that token will lose access and need to re-authenticate. It does NOT delete your account.
  2. Transfer tokens: one-time codes to transfer drop ownership. Generated by `drp send <key>` (24h expiry). Claimed by `drp claim <token>`. Completely separate from API tokens. Not listed in `drp token list`.
  3. Group invite tokens: one-time or limited-use codes to join a group. Created via group management. Completely separate from API tokens and transfer tokens.
Likes: logged-in users can like public drops (toggle). Explore page (/explore/) supports ?sort=likes to sort by most liked (default: most recent). Like counts appear in the JSON API and the explore UI.
Plans: anon, free, starter, pro → drp.fyi/help/plans/
"""


@cache
def _get_docs_context() -> str:
    return _FEATURE_REFERENCE.strip()


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

    model = getattr(settings, "LLM_MODEL", "qwen2.5:1.5b")
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
                "max_tokens": 150,
                "temperature": 0.2,
                "options": {"num_ctx": 2048},
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