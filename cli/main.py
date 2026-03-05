"""
Entry point for the drp CLI.

    drp <command> [args]    → run a single command
"""

from cli.commands import _COMMANDS
from cli.config import get as get_config, get_secret
from cli.defaults import server as default_server
from rich import print

import sys
import shlex


def _resolve_key(parsed_key: str, cmd_func) -> str | None:
    matches = [
        arg for arg in cmd_func.args
        if any(s.lstrip("-") == parsed_key for s in arg.name.split("/"))
    ]
    if len(matches) > 1:
        print(f"[red]✗[/red] Ambiguous flag '-{parsed_key}': matches {', '.join(a.name for a in matches)}")
        return None
    if len(matches) == 1:
        return matches[0].name.split("/")[-1].lstrip("-")
    return parsed_key


def parse_args(raw_args: list[str], cmd_func) -> dict | None:
    positionals = [a for a in cmd_func.args if not a.name.startswith("-")]
    pos_index = 0
    result = {}

    i = 0
    while i < len(raw_args):
        token = raw_args[i]

        if token.startswith("-"):
            key = _resolve_key(token.lstrip("-"), cmd_func)
            if key is None:
                return None
            if i + 1 < len(raw_args) and not raw_args[i + 1].startswith("-"):
                result[key] = raw_args[i + 1]
                i += 2
            else:
                result[key] = True
                i += 1
        else:
            if pos_index < len(positionals):
                result[positionals[pos_index].name] = token
                pos_index += 1
            i += 1

    return result


def validate_args(parsed: dict, cmd_func) -> list[str]:
    errors = []
    for arg in cmd_func.args:
        key = arg.name.split("/")[-1].lstrip("-")
        value = parsed.get(key)

        if arg.required and value is None:
            errors.append(f"Missing required argument: [bold]{arg.name}[/bold] — {arg.description}")
        elif value is not None and arg.choices and value not in arg.choices:
            errors.append(f"Invalid value for [bold]{arg.name}[/bold]: '{value}'. Must be one of: {', '.join(arg.choices)}")

    return errors


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]

    cmd = args[0] if args else "help"

    # drp <command> --help/-h  →  drp help <command>
    if len(args) > 1 and args[1] in ("--help", "-h"):
        _COMMANDS["help"].run({"command": cmd})
        return 0

    cmd_func = _COMMANDS.get(cmd)

    if not cmd_func:
        print("[yellow]Unknown cmd:[/yellow]", cmd)
        return 1

    if cmd_func.run is None:
        print("[yellow]Not implemented yet:[/yellow]", cmd)
        return 1

    parsed = parse_args(shlex.split(" ".join(args[1:])), cmd_func)
    if parsed is None:
        return 1

    errors = validate_args(parsed, cmd_func)
    if errors:
        for err in errors:
            print(f"[red]✗[/red] {err}")
        return 1

    server = get_config("server")
    token = get_secret("token")
    if cmd not in ("login", "help") and not (server and token):
        print("[yellow]No server configured.[/yellow] Run:")
        print(f"  [bold]drp login -s {default_server}[/bold]                       — anonymous session")
        print(f"  [bold]drp login -s {default_server} -u user -p pass -d 30d[/bold] — authenticated session")
        return 1

    try:
        cmd_func.run(parsed)
    except Exception as exc:
        from cli.crash.reporter import report, user_message
        fp = report(cmd, exc, url=f"https://{server}/api/v1/crash/")
        print(f"[red]✗[/red] {user_message(cmd, fp)}")
        return 1

    return 0