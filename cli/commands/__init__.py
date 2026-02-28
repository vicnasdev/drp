"""
cli/commands/__init__.py

Flat command registry — one folder, one registry, no arbitrary splits.
Every command works everywhere: inside the shell, outside, same behaviour.
"""
from .ask     import AskCommand
from .cat     import CatCommand
from .cd      import CdCommand
from .cp      import CpCommand
from .edit    import EditCommand
from .fork    import ForkCommand
from .get     import GetCommand
from .getkey  import GetkeyCommand
from .login   import LoginCommand
from .logout  import LogoutCommand
from .ls      import LsCommand
from .mkdir   import MkdirCommand
from .mv      import MvCommand
from .ping    import PingCommand
from .rm      import RmCommand
from .setkey  import SetkeyCommand
from .setup   import SetupCommand
from .share   import ShareCommand
from .status  import StatusCommand
from .token   import TokenCommand
from .up      import UpCommand

# Single registry used everywhere — shell, CLI, completion
ALL: dict[str, type] = {
    "ask":    AskCommand,
    "cat":    CatCommand,
    "cd":     CdCommand,
    "cp":     CpCommand,
    "edit":   EditCommand,
    "fork":   ForkCommand,
    "get":    GetCommand,
    "getkey": GetkeyCommand,
    "login":  LoginCommand,
    "logout": LogoutCommand,
    "ls":     LsCommand,
    "mkdir":  MkdirCommand,
    "mv":     MvCommand,
    "ping":   PingCommand,
    "rm":     RmCommand,
    "setkey": SetkeyCommand,
    "setup":  SetupCommand,
    "share":  ShareCommand,
    "status": StatusCommand,
    "token":  TokenCommand,
    "up":     UpCommand,
}

# main.py uses OUTSIDE for direct CLI dispatch — now same as ALL
OUTSIDE = ALL
