"""ls — List files and folders."""

from . import Arg, Command, register

cmd = register(Command(
    name="ls",
    description="List files and folders.",
    args=(
        Arg("path",
            "Drive path to list. Defaults to current directory.",
            default="."),
        Arg("--export",
            "Output as JSON for scripting.",
            type="bool"),
        Arg("--sort",
            "Sort by field.",
            choices=("name", "size", "exp")),
    ),
))
