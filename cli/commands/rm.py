"""rm — Delete a file or folder."""

from . import Arg, Command, register
from cli.utils import spin

def run(args):
    print("Soon.")

cmd = register(Command(
    name="rm",
    description="Delete a file or folder.",
    args=(
        Arg("ref",
            "Key, filename, or folder path to delete.",
            required=True),
    ),
    run=spin(run, "Loading")
))
