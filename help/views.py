from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import markdown
from django.shortcuts import render

from cli.commands import Arg, Command, all_commands

# ── README rendering ──────────────────────────────────────────────────────────

_README = Path(__file__).resolve().parent.parent / "README.md"


def _readme_html() -> str:
    """Convert the project README to safe HTML."""
    try:
        text = _README.read_text()
    except FileNotFoundError:
        return "<p>No README found.</p>"
    return markdown.markdown(text, extensions=["fenced_code", "tables"])


# ── CLI template adapters ─────────────────────────────────────────────────────
#
# The help/cli.html template expects a ``parser_info`` context object with
# .description, .commands (list of TemplateCmd), and .epilog.
# Each TemplateCmd has .name, .help, .args (list of TemplateArg), .epilog.
#
# We map our Command / Arg dataclasses into these lightweight wrappers.


@dataclass
class TemplateArg:
    """Thin adapter so the CLI template can render an Arg."""

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
    """Thin adapter so the CLI template can render a Command."""

    name: str
    help: str
    args: list[TemplateArg] = field(default_factory=list)
    epilog: str = ""


def _is_positional(arg: Arg) -> bool:
    return not arg.name.startswith("-")


def _adapt_arg(arg: Arg) -> TemplateArg:
    positional = _is_positional(arg)
    is_flag = arg.type == "bool"
    # Build a display-friendly metavar from the arg name
    metavar = re.sub(r"^-+", "", arg.name).replace("-", "_").upper()
    flags = arg.name if not positional else ""
    return TemplateArg(
        name=arg.name,
        help=arg.description,
        positional=positional,
        flags=flags,
        metavar=metavar,
        is_flag=is_flag,
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
    cmds = all_commands()
    return ParserInfo(
        description="Share text and files from your terminal.",
        commands=[_adapt_command(c) for c in sorted(cmds.values(), key=lambda c: c.name)],
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


from core.models import Plan, plan_display


# ── Plan context helper ───────────────────────────────────────────────────────

def _plans_context():
    """Return context dicts for all plan tiers (guest through pro)."""
    guest = plan_display("anonymous")
    guest["label"] = "Guest"
    free = plan_display(Plan.FREE)
    starter = plan_display(Plan.STARTER)
    pro = plan_display(Plan.PRO)
    return {
        "plans": [
            ("guest", guest),
            ("free", free),
            ("starter", starter),
            ("pro", pro),
        ],
        "guest_limits": guest,
        "free_limits": free,
        "starter_limits": starter,
        "pro_limits": pro,
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
