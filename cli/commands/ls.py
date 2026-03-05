"""ls — List files and folders."""

from . import Arg, Command, register

cmd = register(Command(
    name="ls",
    description="List files and folders.",
    args=(
        Arg("path",
            "Drive path to list. Defaults to root.",
            default="."),
        Arg("--sort",
            "Sort by field.",
            choices=("name", "size", "exp")),
    ),
))
