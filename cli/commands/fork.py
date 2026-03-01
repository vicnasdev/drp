"""fork — Fork a file you don't own into your account."""

from . import Arg, Command, register

cmd = register(Command(
    name="fork",
    description="Copy someone else's file into your account with a new key.",
    args=(
        Arg("key",
            "Key of the file to fork.",
            required=True),
    ),
))
