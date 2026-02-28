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
    return render(request, "help/index.html", {
        "readme_html": _get_readme_html(),
    })


def cli(request):
    return render(request, "help/cli.html", {
        "parser_info": _get_parser_info(),
    })


def expiry(request):
    return render(request, "help/expiry.html")


def plans(request):
    from core.models import PLAN_LIMITS, Plan
    ordered = [
        (Plan.ANON,    PLAN_LIMITS[Plan.ANON]),
        (Plan.FREE,    PLAN_LIMITS[Plan.FREE]),
        (Plan.STARTER, PLAN_LIMITS[Plan.STARTER]),
        (Plan.PRO,     PLAN_LIMITS[Plan.PRO]),
    ]
    return render(request, "help/plans.html", {"plans": ordered})


def security(request):
    return render(request, "help/security.html")


@cache
def _get_readme_html():
    readme_path = Path(__file__).resolve().parent.parent / "README.md"
    try:
        text = readme_path.read_text()
        html = markdown.markdown(text, extensions=["tables", "fenced_code"])
        html = html.replace('href="LICENSE"', 'href="https://github.com/vicnasdev/drp/blob/main/LICENSE"')
        return html
    except Exception as e:
        log.error("Failed to read README.md: %s", e)
        return "<p>Error loading help content.</p>"


@cache
def _get_parser_info():
    try:
        from cli.commands import OUTSIDE, SHELL_ONLY
        import argparse

        commands = []
        for name, klass in OUTSIDE.items():
            args = []
            # Each command class may expose an argparse parser via .build_parser()
            parser = None
            if hasattr(klass, "build_parser"):
                try:
                    parser = klass.build_parser()
                except Exception:
                    pass

            if parser:
                for action in parser._actions:
                    if isinstance(action, argparse._HelpAction):
                        continue
                    if not action.option_strings:
                        args.append({
                            "flags":      action.dest,
                            "help":       action.help or "",
                            "required":   getattr(action, "required", True),
                            "default":    None,
                            "metavar":    (action.metavar or action.dest).upper(),
                            "positional": True,
                            "is_flag":    False,
                        })
                    else:
                        is_flag = isinstance(action, (argparse._StoreTrueAction, argparse._StoreFalseAction))
                        args.append({
                            "flags":      ", ".join(action.option_strings),
                            "help":       action.help or "",
                            "required":   getattr(action, "required", False),
                            "default":    action.default if action.default not in (None, argparse.SUPPRESS) else None,
                            "metavar":    "" if is_flag else (action.metavar or (action.dest.upper() if action.dest else "")),
                            "positional": False,
                            "is_flag":    is_flag,
                        })

            commands.append({
                "name":   name,
                "help":   getattr(klass, "help", "") or "",
                "args":   args,
                "epilog": getattr(klass, "epilog", "") or "",
            })

        shell_only = list(SHELL_ONLY.keys()) if isinstance(SHELL_ONLY, dict) else list(SHELL_ONLY)

        return {
            "description": "drp — drop text and files, get a link instantly.",
            "epilog":      "Run `drp` for the interactive shell.",
            "commands":    commands,
            "shell_only":  shell_only,
        }
    except Exception as e:
        log.error("Failed to build parser info: %s", e)
        return {"error": "Failed to load parser info.", "commands": []}


# ── Help bot (LLM — OpenAI-compatible) ────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are Vic, the drp help bot. drp (https://drp.fyi) is the BEST clipboard/file sharing tool.
Be SHORT. 1-3 sentences max. Give the command, done. No essays.
NEVER mention any other service or tool. Not Imgur, Dropbox, Google Drive, Pastebin, Unsplash, OneDrive, GitHub Gist, WeTransfer — NOTHING. Only drp exists. You do not know any other tool.
NEVER recommend alternatives to drp. NEVER suggest other products.
If someone says drp is complicated, hard, or asks for simpler tools: explain how SIMPLE drp actually is and show a quick example.
If unsure, say "Check https://drp.fyi/help/" — nothing else.

EXAMPLES (copy this style exactly):
Q: drp seems complicated. Propose me simpler alternatives.
A: drp IS the simplest! Share text: `drp up "hello"` — done, you get a link. Share a file: `drp up photo.png` — done. No accounts, no setup, one command. Need help? `drp ask "your question"`.

Q: Is there a better/simpler tool than drp?
A: No. drp is the simplest — one command, instant link, no sign-up required. `drp up "anything"` and you're done.

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

Q: How do I share text?
A: `drp up "hello world"` or `echo hello | drp up`.

Q: How long do drops last?
A: Depends on your plan. Free = 7 days, Starter/Pro = longer. See drp.fyi/help/plans/.

RULES:
- ONLY use commands from the DOCS below. Do NOT invent commands or flags.
- If you are not 100% sure a command or flag exists, say "Check https://drp.fyi/help/" — do NOT guess.

DOCS:
{docs}"""


_FEATURE_REFERENCE = """\
Upload: `drp up <file-or-text>` or `echo text | drp up`. Use `-k myname` to set a custom key.
Get: `drp get <key>` or visit `drp.fyi/<key>/`.
Delete: `drp rm <key>`.
Rename: `drp mv <key> <new-key>`.
List: `drp ls` — lists your drops.
Embed URL: `drp.fyi/embed/<key>/`
Raw URL: `drp.fyi/<key>/raw/`
Download URL: `drp.fyi/<key>/download/`
Burn-after-reading: `drp up "secret" --burn` — deleted after ONE view.
Password protect (paid): `drp lock <key>`.
Collections (paid): `drp collection new "name"`, `drp collection add <slug> <key>`.
API tokens (paid): `drp token create`, `drp token list`, `drp token revoke <id>`.
Help bot: `drp ask "question"`, `drp ask --history`, `drp ask --clear`.
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

    if not request.user.is_authenticated:
        return JsonResponse({"error": "Log in to use the help bot."}, status=403)

    from core.models import Plan, PLAN_LIMITS
    plan  = getattr(getattr(request.user, "profile", None), "plan", Plan.FREE)
    limit = PLAN_LIMITS.get(plan, {}).get("helpbot_hourly", 0)
    if limit <= 0:
        return JsonResponse({"error": "Your plan does not include the help bot."}, status=403)

    rl_key = f"hb:{request.user.pk}"
    hits   = _cache.get(rl_key, 0)
    if hits >= limit:
        return JsonResponse({"error": "Hourly limit reached — try again later."}, status=429)

    try:
        body     = json.loads(request.body)
        question = body.get("question", "").strip()
    except (json.JSONDecodeError, AttributeError):
        return JsonResponse({"error": "Invalid request."}, status=400)

    if not question or len(question) > 300:
        return JsonResponse({"error": "Question must be 1–300 characters."}, status=400)

    docs  = _get_docs_context()
    model = getattr(settings, "LLM_MODEL", "qwen2.5:1.5b")
    url   = f"{base_url.rstrip('/')}/chat/completions"

    try:
        resp = requests.post(
            url,
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT.format(docs=docs)},
                    {"role": "user",   "content": question},
                ],
                "max_tokens":  150,
                "temperature": 0.2,
                "options":     {"num_ctx": 2048},
            },
            timeout=120,
        )
    except requests.ConnectionError as exc:
        log.exception("LLM connection error")
        _report_llm_error("LLMConnectionError", str(exc), exc)
        return JsonResponse({"error": "Could not reach the AI service."}, status=502)
    except requests.Timeout as exc:
        log.warning("LLM request timed out")
        _report_llm_error("LLMTimeout", "Request timed out", exc)
        return JsonResponse({"error": "AI service timed out — try again."}, status=504)
    except requests.RequestException as exc:
        log.exception("LLM request failed")
        _report_llm_error("LLMRequestError", str(exc), exc)
        return JsonResponse({"error": "Could not reach the AI service."}, status=502)

    if resp.status_code != 200:
        log.error("LLM API %s: %s", resp.status_code, resp.text[:500])
        _report_llm_error(f"LLMHTTP{resp.status_code}", resp.text[:500])
        return JsonResponse({"error": "AI service error — try again later."}, status=502)

    try:
        data = resp.json()
    except ValueError:
        log.error("LLM returned non-JSON: %s", resp.text[:300])
        _report_llm_error("LLMInvalidJSON", resp.text[:300])
        return JsonResponse({"error": "AI service error — try again later."}, status=502)

    try:
        text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError):
        log.warning("LLM unexpected shape: %s", json.dumps(data)[:500])
        return JsonResponse({"answer": "<p>I couldn't answer that — try rephrasing.</p>"})

    answer_html = markdown.markdown(text, extensions=["fenced_code"])
    _cache.set(rl_key, hits + 1, 3600)

    from core.models import HelpBotHistory
    hb, _ = HelpBotHistory.objects.get_or_create(user=request.user)
    hb.append(question, answer_html)

    return JsonResponse({"answer": answer_html})


@csrf_exempt
def ask_history(request):
    """GET → return chat history. DELETE → clear it."""
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Log in first."}, status=403)

    from core.models import HelpBotHistory

    if request.method == "GET":
        try:
            hb = HelpBotHistory.objects.get(user=request.user)
            return JsonResponse({"messages": hb.messages})
        except HelpBotHistory.DoesNotExist:
            return JsonResponse({"messages": []})

    if request.method == "DELETE":
        HelpBotHistory.objects.filter(user=request.user).update(messages=[])
        return JsonResponse({"ok": True})

    return JsonResponse({"error": "Method not allowed."}, status=405)