"""
cli/shell.py

Interactive shell loop. Launched when `drp` is run with no arguments.

Features:
  - Context-aware prompt:  drp:/@vic/docs>
  - Tab completion for commands and paths
  - Pipe support:          ls | grep py
  - Ctrl-C cancels current command, Ctrl-D exits
"""
from __future__ import annotations

import shlex
import sys

from cli import commands as cmd_registry
from cli.base.color import Color
from cli.crash.reporter import CrashReporter


def run_shell(config: dict, reporter: CrashReporter | None = None) -> None:
    _setup_readline(config)
    print(Color.dim("drp shell — type 'help' for commands, Ctrl-D to exit"))
    print()

    while True:
        try:
            line = input(_prompt(config)).strip()
        except EOFError:
            print()
            break
        except KeyboardInterrupt:
            print()
            continue

        if not line:
            continue

        # pipe handling:  ls | grep py
        if "|" in line:
            _run_piped(line, config, reporter)
            continue

        parts = shlex.split(line)
        name  = parts[0]
        args  = parts[1:]

        if name in ("exit", "quit"):
            break

        if name == "help":
            _print_help()
            continue

        klass = cmd_registry.ALL.get(name)
        if klass is None:
            print(Color.error("error: ") + f"unknown command: {name}")
            print(Color.dim(f"  type 'help' to see available commands"))
            continue

        cmd = klass(config, reporter=reporter, in_shell=True)
        cmd.execute(args)


# ------------------------------------------------------------------ prompt

def _prompt(config: dict) -> str:
    cwd      = config.get("shell", {}).get("cwd", "/")
    username = config.get("auth", {}).get("username", "")
    path     = f"/@{username}{cwd}" if username else cwd
    return Color.wrap("drp", Color.CYAN, Color.BOLD) + Color.dim(f":{path}> ")


# ------------------------------------------------------------------ pipe

def _run_piped(line: str, config: dict, reporter) -> None:
    import subprocess, io
    segments = [s.strip() for s in line.split("|")]
    buf      = None

    for i, seg in enumerate(segments):
        parts = shlex.split(seg)
        name  = parts[0]
        args  = parts[1:]

        klass = cmd_registry.ALL.get(name)
        if klass is None:
            if buf is not None:
                proc = subprocess.run(seg, shell=True, input=buf, capture_output=False, text=True)
            return

        import io as _io
        old_stdout = sys.stdout
        sys.stdout = captured = _io.StringIO()
        try:
            cmd = klass(config, reporter=reporter, in_shell=True)
            cmd.execute(args)
        finally:
            sys.stdout = old_stdout
        buf = captured.getvalue()

    if buf:
        print(buf, end="")


# ------------------------------------------------------------------ completion

def _setup_readline(config: dict) -> None:
    try:
        import readline
        cmds = list(cmd_registry.ALL.keys()) + ["help", "exit"]

        def completer(text, state):
            # FIX 1: always guard with try/except — any uncaught exception here
            # causes readline to spin calling the completer forever, freezing
            # the terminal with no visible output.
            try:
                options = [c for c in cmds if c.startswith(text)]
                if state < len(options):
                    return options[state]
                return None
            except Exception:
                return None

        readline.set_completer(completer)

        # FIX 2: without set_completer_delims, readline treats every character
        # as a potential delimiter and over-calls the completer.
        readline.set_completer_delims(" \t\n")

        # FIX 3: the "freeze" the user sees is readline's built-in pagination:
        # when tab is pressed with no text, all N commands match and readline
        # silently waits for "Display all N possibilities? (y/n)" with no
        # visible prompt. Setting completion-query-items high enough prevents
        # this prompt from ever appearing.
        readline.parse_and_bind("set completion-query-items 9999")
        readline.parse_and_bind("tab: complete")

    except ImportError:
        pass  # readline unavailable on Windows


# ------------------------------------------------------------------ help

def _print_help() -> None:
    from cli.base.color import Color
    print()
    print(Color.dim("  available commands"))
    print(Color.dim("  " + "─" * 36))
    for name, klass in cmd_registry.ALL.items():
        desc = getattr(klass, "description", "")
        print(f"  {Color.key(name.ljust(10))}  {Color.dim(desc)}")
    print()