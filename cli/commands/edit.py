"""edit — Open a drive file in $EDITOR and re-upload if changed."""

from . import Arg, Command, register

cmd = register(Command(
    name="edit",
    description="Fetch a drive file, open in $EDITOR, re-upload if changed.",
    shell_only=True,
    args=(
        Arg("filename",
            "Filename in the current drive folder.",
            required=True),
        Arg("--editor",
            "Override $EDITOR, e.g. --editor nano."),
        Arg("--decrypt",
            "Decrypt before editing, re-encrypt before re-uploading.",
            type="passphrase"),
    ),
))
