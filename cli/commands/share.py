"""share — Create and manage share tokens for folders."""

from . import Arg, Command, register

cmd = register(Command(
    name="share",
    description="Create and manage share tokens for folders.",
    shell_only=True,
    args=(
        Arg("action",
            "Subcommand: omit to create, 'list' to list, 'revoke' to revoke.",
            default="create", choices=("create", "list", "revoke")),
        Arg("target",
            "Folder path (for create/list) or token ID (for revoke)."),
        Arg("--write",
            "Grant write access (recipient can upload into the folder).",
            type="bool"),
        Arg("--admin",
            "Grant admin access (recipient can delete and rename).",
            type="bool"),
        Arg("--expires",
            "Token expiry, e.g. 7d, 30d.",
            type="duration"),
    ),
))
