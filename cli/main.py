"""
cli/main.py

CLI entrypoint. Dispatches to shell or direct command mode.

  drp              → interactive shell
  drp <cmd> ...    → direct command
  drp --no-color   → disable color globally
"""
from __future__ import annotations

import sys

from cli import config as cfg
from cli.base.color import Color
from cli.crash.reporter import CrashReporter
from cli import commands as cmd_registry
from cli.shell import run_shell


def main() -> None:
    args = sys.argv[1:]

    # --no-color anywhere in args
    if "--no-color" in args:
        Color.disable()
        args = [a for a in args if a != "--no-color"]

    config   = cfg.load()
    reporter = CrashReporter(config.get("server", {}).get("url", "https://drp.fyi"))

    # no args → interactive shell
    if not args:
        run_shell(config, reporter)
        return

    name = args[0]
    rest = args[1:]

    # shell completion hook
    if name == "--completion":
        _print_completion(rest[0] if rest else "bash")
        return

    klass = cmd_registry.OUTSIDE.get(name)
    if klass is None:
        if name in cmd_registry.SHELL_ONLY:
            print(Color.error("error: ") + f"'{name}' is only available inside the drp shell")
            print(Color.dim("  run: drp  (then use the shell)"))
        else:
            print(Color.error("error: ") + f"unknown command: {name}")
            print(Color.dim("  run: drp --help"))
        sys.exit(1)

    cmd  = klass(config, reporter=reporter, in_shell=False)
    code = cmd.execute(rest)
    sys.exit(code)


def _print_completion(shell: str) -> None:
    cmds = " ".join(cmd_registry.OUTSIDE.keys())
    flags = {
        "up":     "--text --key --burn --password --encrypt --expires --public --tag --schedule --webhook",
        "get":    "--raw --out",
        "ls":     "--export",
        "login":  "--token --browser",
        "status": "",
        "ping":   "",
        "token":  "--revoke",
        "ask":    "",
        "logout": "",
        "setup":  "",
    }
    if shell == "bash":
        print(f'complete -W "{cmds}" drp')
        for cmd, f in flags.items():
            if f:
                print(f'complete -W "{f}" -c drp_{cmd} 2>/dev/null || true')
        # Main completion function — no execution, purely static
        print("""
_drp_complete() {
    local cur prev words
    COMPREPLY=()
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"
    local cmds="""" + cmds + """"
    local cmd=""
    for w in "${COMP_WORDS[@]}"; do
        case "$w" in up|get|ls|login|logout|status|ping|token|ask|setup) cmd=$w; break;; esac
    done
    case "$cmd" in""")
        for cmd, f in flags.items():
            print(f'        {cmd}) COMPREPLY=( $(compgen -W "{f}" -- "$cur") $(compgen -f -- "$cur") ); return ;;')
        print('    esac')
        print('    COMPREPLY=( $(compgen -W "$cmds" -- "$cur") )')
        print('}; complete -F _drp_complete drp')
    elif shell == "zsh":
        print(f'compdef "_arguments \'1:command:(({cmds}))\'" drp')
    elif shell == "fish":
        for c in cmd_registry.OUTSIDE:
            print(f"complete -c drp -f -a {c}")
        for cmd, f in flags.items():
            for flag in f.split():
                print(f"complete -c drp -n '__fish_seen_subcommand_from {cmd}' -l {flag.lstrip('-')}")


if __name__ == "__main__":
    main()