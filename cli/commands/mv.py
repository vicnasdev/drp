"""mv — Rename or move a file within the drive."""

from . import Arg, Command, register

cmd = register(Command(
    name="mv",
    description="Rename or move a file within the drive. No re-upload — server-side update.",
    shell_only=True,
    args=(
        Arg("src",
            "Current drive path or filename.",
            required=True),
        Arg("dest",
            "New drive path or filename.",
            required=True),
    ),
))
