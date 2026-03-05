"""up — Upload a file, directory, glob, or text."""

from . import Arg, Command, register
from cli.utils import spin

def run(args):
    print("Soon.")

cmd = register(Command(
    name="up",
    description="Upload a file, directory, glob, or text.",
    args=(
        Arg("target",
            "Local file path, glob (\"*.py\"), - for stdin, or literal text with --text.",
            required=True, type="path"),
        Arg("--key",
            "Custom key. Format: [a-zA-Z0-9_-]{1,64}. Rejected if taken."),
        Arg("--expires",
            "Key expiry: 7d, 24h, 30m. Capped at plan max. Defaults to plan max.",
            type="duration"),
        Arg("--publish",
            "List the file on /explore/ and your profile.",
            type="bool"),
        Arg("--burn",
            "Invalidate the key after the first view.",
            type="bool"),
        Arg("--password",
            "Require a password to access the key. Starter/Pro only.",
            type="passphrase"),
        Arg("--encryption-key",
            "Client-side AES encryption before upload. Server never sees plaintext.",
            type="passphrase"),
        Arg("--tag",
            "Add a tag. Repeatable: --tag python --tag snippet.",
            repeatable=True),
        Arg("--text",
            "Treat target as literal text content, not a filename.",
            type="bool"),
    ),
    run=spin(run, "Loading")
))
