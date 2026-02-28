"""
cli/shell.py

Interactive shell loop. Launched when `drp` is run with no arguments.
Opens at @username/ scoped to the directory drp was launched from.
"""
from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path

from cli import commands as cmd_registry
from cli.base.color import Color
from cli.cache import drive_cache
from cli.crash.reporter import CrashReporter


def run_shell(config: dict, reporter: CrashReporter | None = None) -> None:
    _init_cwd(config)
    _setup_readline(config)
    drive_cache.start(config)   # load disk cache + start background refresh thread
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

        # Strip shell-style comments before parsing.
        # This must happen before shlex.split — an apostrophe in a comment
        # (e.g. "# doesn't work") causes ValueError: No closing quotation.
        line = _strip_comment(line)
        if not line:
            continue

        if "|" in line:
            _run_piped(line, config, reporter)
            continue

        try:
            parts = shlex.split(line)
        except ValueError as exc:
            print(Color.error("parse error: ") + str(exc))
            continue
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
            print(Color.dim("  type 'help' to see available commands"))
            continue

        cmd = klass(config, reporter=reporter, in_shell=True)
        cmd.execute(args)

        # Invalidate the drive cache after any write command so autocomplete
        # reflects new files/folders on the very next Tab press.
        _WRITE_CMDS = {"up", "cp", "mv", "rm", "mkdir"}
        if name in _WRITE_CMDS:
            drive_cache.invalidate()


# ------------------------------------------------------------------ init

def _init_cwd(config: dict) -> None:
    """
    Set the initial virtual CWD to the real directory drp was launched from.
    drp opened in ~/Desktop/Code/temp/ → virtual CWD is /temp/
    Prompt shows /@vicnas/temp/
    The folder is created in drp if it doesn't exist yet.
    """
    slug     = Path(os.getcwd()).name
    username = config.get("auth", {}).get("username", "")
    if not username:
        return

    shell = config.setdefault("shell", {})
    if shell.get("cwd_id"):
        return  # already initialised (shouldn't happen on fresh launch but be safe)

    shell["cwd"]      = f"/{slug}"
    shell["cwd_slug"] = slug

    # Ensure the folder exists on the server, get its id
    try:
        from cli.api.client import APIClient
        from cli.api import folders as folders_api
        client = APIClient.from_config(config, authed=True)
        try:
            result = folders_api.create(client, slug)
        except Exception:
            # Already exists — find it
            data   = folders_api.list_root(client)
            result = next((f for f in data.get("folders", []) if f["slug"] == slug), {})
        shell["cwd_id"] = result.get("id")
    except Exception:
        shell["cwd_id"] = None


# ------------------------------------------------------------------ prompt

def _prompt(config: dict) -> str:
    cwd      = config.get("shell", {}).get("cwd", "/")
    username = config.get("auth", {}).get("username", "")
    path     = f"/@{username}{cwd}" if username else cwd
    return Color.wrap("drp", Color.CYAN, Color.BOLD) + Color.dim(f":{path}> ")


# ------------------------------------------------------------------ pipe

def _run_piped(line: str, config: dict, reporter) -> None:
    import subprocess
    segments = [s.strip() for s in line.split("|")]
    buf      = None

    for seg in segments:
        parts = shlex.split(seg)
        name  = parts[0]
        args  = parts[1:]

        klass = cmd_registry.ALL.get(name)
        if klass is None:
            if buf is not None:
                subprocess.run(seg, shell=True, input=buf, capture_output=False, text=True)
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
    """
    Wire up Tab completion. The completer reads ONLY from drive_cache's
    in-memory snapshot — no I/O, no network, always returns instantly.
    The background thread in drive_cache keeps that snapshot fresh.
    """
    try:
        import readline

        cmds = list(cmd_registry.ALL.keys()) + ["help", "exit"]

        def completer(text, state):
            try:
                buf   = readline.get_line_buffer()
                parts = buf.lstrip().split()

                # Completing the command name (first token)
                if len(parts) == 0 or (len(parts) == 1 and not buf.endswith(" ")):
                    options = [c for c in cmds if c.startswith(text)]
                    return options[state] if state < len(options) else None

                # Completing an argument
                if text.startswith("../") or text.startswith("./") \
                        or text == ".." or text == ".":
                    # Real filesystem path
                    real_prefix = str(Path(text).parent) if "/" in text else "."
                    real_part   = text.rsplit("/", 1)[-1] if "/" in text else text
                    try:
                        entries = os.listdir(real_prefix)
                        matches = [
                            (real_prefix.rstrip("/") + "/" + e if real_prefix != "." else e)
                            for e in entries if e.startswith(real_part)
                        ]
                    except Exception:
                        matches = []
                else:
                    # drp path — read from in-memory cache only, zero I/O
                    cwd_id  = config.get("shell", {}).get("cwd_id")
                    names   = drive_cache.get_names(cwd_id)
                    matches = [n for n in names if n.startswith(text)]

                return matches[state] if state < len(matches) else None

            except Exception:
                return None

        readline.set_completer(completer)
        readline.set_completer_delims(" \t\n")
        readline.parse_and_bind("set page-completions off")
        readline.parse_and_bind("set completion-query-items 0")
        readline.parse_and_bind("tab: complete")

    except ImportError:
        pass


# ------------------------------------------------------------------ comment stripping

def _strip_comment(line: str) -> str:
    """
    Strip an unquoted '#' and everything after it, respecting quotes.
    Returns the line stripped of the comment and trailing whitespace.
    """
    in_single = False
    in_double = False
    for i, ch in enumerate(line):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == '#' and not in_single and not in_double:
            return line[:i].rstrip()
    return line

def _print_help() -> None:
    print()
    print(Color.dim("  available commands"))
    print(Color.dim("  " + "─" * 36))
    for name, klass in cmd_registry.ALL.items():
        desc = getattr(klass, "description", "")
        print(f"  {Color.key(name.ljust(10))}  {Color.dim(desc)}")
    print()