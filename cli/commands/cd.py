"""cd — Change the virtual working directory."""

from . import Arg, Command, register

cmd = register(Command(
    name="cd",
    description="Change the virtual working directory.",
    shell_only=True,
    args=(
        Arg("path",
            "Subfolder, .., /, or @username to browse another user's public drive.",
            required=True),
    ),
))
