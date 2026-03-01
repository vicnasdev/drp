"""getkey — Print the key for a file looked up by filename."""

from . import Arg, Command, register

cmd = register(Command(
    name="getkey",
    description="Print the key for a file in the current drive folder.",
    shell_only=True,
    args=(
        Arg("filename",
            "Filename to look up.",
            required=True),
    ),
))
