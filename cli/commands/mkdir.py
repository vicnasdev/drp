"""mkdir — Create a folder at the current drive location."""

from . import Arg, Command, register

cmd = register(Command(
    name="mkdir",
    description="Create a folder at the current drive location.",
    shell_only=True,
    args=(
        Arg("name",
            "Name for the new folder.",
            required=True),
    ),
))
