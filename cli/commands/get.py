"""get — Download a file to disk."""

from . import Arg, Command, register
from cli.utils import spin

def run(args):
    print("Soon.")

cmd = register(Command(
    name="get",
    description="Download a file to disk.",
    args=(
        Arg("path",
            "Path on the drive",
            required=False),
        Arg(
            "--key",
            "Key of a file"
        ),
        Arg("--destination",
            "Desination path."),
        Arg("--encryption-key",
            "Passphrase for client-side encrypted content. Decrypts after download.",
            type="passphrase"),
    ),
    run=spin(run, "Loading")
))
