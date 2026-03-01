"""cat — Display a file's content in the terminal with syntax highlighting."""

from . import Arg, Command, register

cmd = register(Command(
    name="cat",
    description="Display a file's content in the terminal with syntax highlighting.",
    args=(
        Arg("ref",
            "A key (xK9mZ2) or filename in the current drive folder (shell only).",
            required=True),
        Arg("--encryption-key",
            "Passphrase for client-side encrypted content. Decrypts in memory for display.",
            type="passphrase"),
        Arg("--parse",
            "Parse and pretty-print. JSON is formatted; CSV rendered as a table.",
            type="bool"),
        Arg("--field",
            "Extract a single field. JSON: dot-notation. CSV: column name or index. Implies --parse."),
        Arg("--highlight",
            "Force a syntax lexer, e.g. --highlight python. Overrides auto-detection."),
    ),
))
