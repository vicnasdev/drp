"""
DrpShell — cmd2-based REPL for drp.

Dynamically registers every command in ``cli.commands`` as a ``do_*``
method so the registry is the single source of truth.
"""

from __future__ import annotations

import textwrap

import cmd2

from cli import __version__
from cli.commands import Command, all_commands


# ── Shell ─────────────────────────────────────────────────────────────────────


def _build_help(spec: Command) -> str:
    """Format a rich help string from a Command spec."""
    lines = [spec.description, ""]
    if spec.args:
        lines.append("Arguments:")
        for arg in spec.args:
            tag = f"  {arg.name}"
            if arg.required:
                tag += "  (required)"
            lines.append(tag)
            lines.append(f"      {arg.description}")
            if arg.choices:
                lines.append(f"      choices: {', '.join(arg.choices)}")
            if arg.repeatable:
                lines.append("      (repeatable)")
        lines.append("")
    if spec.shell_only:
        lines.append("Shell only — not available as a standalone command.")
    return "\n".join(lines)


class DrpShell(cmd2.Cmd):
    """Interactive drp shell."""

    intro = f"drp {__version__} — type 'help' for commands, Ctrl-D to exit.\n"

    def __init__(self, *, username: str = "", **kwargs):
        super().__init__(**kwargs)
        self.username = username
        self.cwd = "/"          # virtual working directory
        self._update_prompt()
        self.hidden_commands.extend(["alias", "macro", "run_pyscript",
                                     "run_script", "edit", "shell", "set",
                                     "shortcuts"])

    # ── Prompt ────────────────────────────────────────────────────

    def _update_prompt(self):
        user = f"@{self.username}" if self.username else ""
        self.prompt = f"\033[36mdrp\033[0m:\033[33m/{user}{self.cwd}\033[0m> "

    # ── Dynamic command registration ──────────────────────────────

    @classmethod
    def _register_commands(cls):
        """Create ``do_*`` and ``help_*`` methods from the command registry."""
        for name, spec in all_commands().items():
            _install_command(cls, spec)

    # ── Error handling ────────────────────────────────────────────

    def onecmd(self, statement, *args, **kwargs):
        """Wrap every command dispatch with crash reporting."""
        try:
            return super().onecmd(statement, *args, **kwargs)
        except Exception as exc:
            from cli.crash.reporter import report, user_message

            cmd_name = (
                statement.command
                if hasattr(statement, "command")
                else str(statement).split()[0]
            )
            fp = report(cmd_name, exc)
            self.perror(user_message(cmd_name, fp))

    # ── Fallback ──────────────────────────────────────────────────

    def default(self, statement: cmd2.Statement):
        self.poutput(f"unknown command: {statement.command}")


def _install_command(cls, spec: Command):
    """Attach a stub ``do_<name>`` and ``help_<name>`` to *cls*."""
    help_text = _build_help(spec)

    def do_func(self, statement: cmd2.Statement):  # noqa: ARG001
        self.poutput(f"[stub] {spec.name} — not yet implemented")

    do_func.__doc__ = spec.description
    do_func.__name__ = f"do_{spec.name}"

    def help_func(self):
        self.poutput(help_text)

    help_func.__name__ = f"help_{spec.name}"

    setattr(cls, f"do_{spec.name}", do_func)
    setattr(cls, f"help_{spec.name}", help_func)


# Register once at import time.
DrpShell._register_commands()
