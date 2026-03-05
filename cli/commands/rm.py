"""rm — Delete a file or folder."""

from . import Arg, Command, register

cmd = register(Command(
    name="rm",
    description="Delete a file or folder.",
    args=(
        Arg("ref",
            "Key, filename, or folder path to delete.",
            required=True),
    ),
))
