"""
cli/commands/__init__.py

Command registry. Adding a new command = one line here + one new file.
Nothing else to touch.
"""
from cli.commands.both    import UpCommand, GetCommand, LsCommand, StatusCommand, TokenCommand, AskCommand
from cli.commands.outside import SetupCommand, LoginCommand, LogoutCommand, PingCommand
from cli.commands.shell   import (
    CdCommand, MkdirCommand, CatCommand, CpCommand, MvCommand, RmCommand,
    GetkeyCommand, SetkeyCommand, EditCommand, ForkCommand, ShareCommand,
)

# Commands available outside the shell
OUTSIDE: dict[str, type] = {
    "up":     UpCommand,
    "get":    GetCommand,
    "ls":     LsCommand,
    "status": StatusCommand,
    "token":  TokenCommand,
    "ask":    AskCommand,
    "login":  LoginCommand,
    "logout": LogoutCommand,
    "setup":  SetupCommand,
    "ping":   PingCommand,
}

# Additional commands available only inside the shell
SHELL_ONLY: dict[str, type] = {
    "cd":     CdCommand,
    "mkdir":  MkdirCommand,
    "cat":    CatCommand,
    "cp":     CpCommand,
    "mv":     MvCommand,
    "rm":     RmCommand,
    "getkey": GetkeyCommand,
    "setkey": SetkeyCommand,
    "edit":   EditCommand,
    "fork":   ForkCommand,
    "share":  ShareCommand,
}

# Full registry used inside the shell
ALL: dict[str, type] = {**OUTSIDE, **SHELL_ONLY}
