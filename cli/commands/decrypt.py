"""decrypt — Permanently remove client-side encryption from a file."""

from . import Arg, Command, register

cmd = register(Command(
    name="decrypt",
    description="Permanently decrypt a file. Downloads, decrypts, and re-uploads without encryption.",
    args=(
        Arg("ref",
            "Key (xK9mZ2) or filename in the current drive folder (shell only).",
            required=True),
        Arg("encryption_key",
            "The passphrase used to encrypt the file.",
            required=True, type="passphrase"),
    ),
))
