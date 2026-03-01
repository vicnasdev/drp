"""setkey — Rename a file's key."""

from . import Arg, Command, register

cmd = register(Command(
    name="setkey",
    description="Rename a file's key. The old key stops working immediately.",
    shell_only=True,
    args=(
        Arg("filename",
            "Current filename in the drive folder.",
            required=True),
        Arg("newkey",
            "New key. Format: [a-zA-Z0-9_-]{1,64}.",
            required=True),
    ),
))
