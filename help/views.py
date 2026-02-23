import json
import re
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


# ── Help bot (Gemini Flash) ──────────────────────────────────────────────────

_GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/"
    "models/gemini-2.0-flash:generateContent"
)

_SYSTEM_PROMPT = """\
You are the help assistant for drp (https://drp.fyi), a clipboard and file \
sharing service. Answer questions using ONLY the documentation below.
Be concise — 150 words or fewer. Use markdown for code and emphasis.
If the answer is not in the docs, say so.

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
    s = _TagStripper()
    s.feed(text)
    return s.get_text()


@cache
def _get_docs_context() -> str:
    base = Path(__file__).resolve().parent.parent
    parts = [(base / "README.md").read_text()]
    tmpl_dir = base / "project" / "templates" / "help"
    for name in ("expiry.html", "plans.html", "cli.html"):
        p = tmpl_dir / name
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


def _client_ip(request) -> str:
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return xff.split(",")[0].strip() if xff else request.META.get("REMOTE_ADDR", "")


@csrf_exempt
@require_POST
def ask(request):
    api_key = getattr(settings, "GEMINI_API_KEY", "")
    if not api_key:
        return JsonResponse({"error": "Help bot is not configured."}, status=503)

    ip = _client_ip(request)
    rl_key = f"hb:{ip}"
    hits = _cache.get(rl_key, 0)
    if hits >= 10:
        return JsonResponse(
            {"error": "Too many questions — try again in an hour."}, status=429,
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

    try:
        resp = requests.post(
            f"{_GEMINI_URL}?key={api_key}",
            json={
                "contents": [{"role": "user", "parts": [{"text": question}]}],
                "systemInstruction": {
                    "parts": [{"text": _SYSTEM_PROMPT.format(docs=docs)}],
                },
                "generationConfig": {
                    "maxOutputTokens": 400,
                    "temperature": 0.3,
                },
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException:
        return JsonResponse(
            {"error": "Could not reach the AI service."}, status=502,
        )

    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        return JsonResponse(
            {"answer": "<p>I couldn't answer that — try rephrasing.</p>"},
        )

    answer_html = markdown.markdown(text, extensions=["fenced_code"])
    _cache.set(rl_key, hits + 1, 3600)
    return JsonResponse({"answer": answer_html})