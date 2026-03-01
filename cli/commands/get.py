"""get — Download a file to disk."""

from . import Arg, Command, register

cmd = register(Command(
    name="get",
    description="Download a file to disk.",
    args=(
        Arg("key",
            "Bare key (xK9mZ2), full URL, or share URL containing ?t=.",
            required=True),
        Arg("-n/--name",
            "Save with a different filename instead of the original."),
        Arg("--fork",
            "Fork the file into your own account instead of downloading.",
            type="bool"),
        Arg("--decrypt",
            "Decrypt client-side encrypted content after download.",
            type="passphrase"),
        Arg("--stdout",
            "Write content to stdout instead of a file. Enables piping.",
            type="bool"),
    ),
))
