"""get — Download a file to disk."""

from . import Arg, Command, register

cmd = register(Command(
    name="get",
    description="Download a file to disk.",
    args=(
        Arg("path",
            "Path on the drive",
            required=True),
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
))
