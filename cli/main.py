"""
Entry point for the drp CLI.

    drp <command> [args]    → run a single command
"""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]

    from cli.shell import DrpShell

    shell = DrpShell()

    try:
        if not args:
            shell.cmdloop()
        else:
            line = " ".join(args)
            shell.onecmd_plus_hooks(line)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        from cli.crash.reporter import report, user_message

        cmd = args[0] if args else "shell"
        fp = report(cmd, exc)
        print(user_message(cmd, fp), file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
