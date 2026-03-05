from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import markdown
from django.shortcuts import render

from cli.commands import Arg, Command, _COMMANDS
from core.models import LIMITS, Plan

# ── README rendering ──────────────────────────────────────────────────────────

_README = Path(__file__).resolve().parent.parent / "README.md"


def _readme_html() -> str:
    try:
        text = _README.read_text()
    except FileNotFoundError:
        return "<p>No README found.</p>"
    return markdown.markdown(text, extensions=["fenced_code", "tables"])


# ── CLI template adapters ─────────────────────────────────────────────────────

@dataclass
class TemplateArg:
    name: str
    help: str
    positional: bool
    flags: str
    metavar: str
    is_flag: bool
    required: bool
    default: str | None


@dataclass
class TemplateCmd:
    name: str
    help: str
    args: list[TemplateArg] = field(default_factory=list)
    epilog: str = ""


def _adapt_arg(arg: Arg) -> TemplateArg:
    positional = not arg.name.startswith("-")
    return TemplateArg(
        name=arg.name,
        help=arg.description,
        positional=positional,
        flags=arg.name if not positional else "",
        metavar=re.sub(r"^-+", "", arg.name).replace("-", "_").upper(),
        is_flag=arg.type == "bool",
        required=arg.required,
        default=str(arg.default) if arg.default is not None else "",
    )


def _adapt_command(cmd: Command) -> TemplateCmd:
    return TemplateCmd(
        name=cmd.name,
        help=cmd.description,
        args=[_adapt_arg(a) for a in cmd.args],
    )


@dataclass
class ParserInfo:
    description: str
    commands: list[TemplateCmd]
    epilog: str


def _parser_info() -> ParserInfo:
    return ParserInfo(
        description="Share text and files from your terminal.",
        commands=[_adapt_command(c) for c in sorted(_COMMANDS.values(), key=lambda c: c.name)],
        epilog=(
            "# push text\n"
            "echo 'hello' | drp up\n\n"
            "# push a file\n"
            "drp up -f notes.txt\n\n"
            "# pull\n"
            "drp cat mykey\n\n"
            "# interactive shell\n"
            "drp shell"
        ),
    )


# ── Plan context helper ───────────────────────────────────────────────────────

def _plans_context():
    return {
        f"{plan.value}_limits": LIMITS[plan]
        for plan in Plan
    }


# ── Views ─────────────────────────────────────────────────────────────────────

def help_index(request):
    return render(request, "help/index.html", {"readme_html": _readme_html()})


def help_cli(request):
    return render(request, "help/cli.html", {"parser_info": _parser_info()})


def help_plans(request):
    return render(request, "help/plans.html", _plans_context())


def help_expiry(request):
    return render(request, "help/expiry.html", _plans_context())


def help_security(request):
    return render(request, "help/security.html")