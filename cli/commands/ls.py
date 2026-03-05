"""ls — List files and folders."""

from . import Arg, Command, register
from cli.utils import spin

def run(args):
    print("Soon.")

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
    run=spin(run, "Loading")
))
