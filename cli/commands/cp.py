"""cp — Copy files between the real filesystem and the drive, or within the drive."""

from . import Arg, Command, register

cmd = register(Command(
    name="cp",
    description="Copy files between the real filesystem and the drive, or within the drive.",
    shell_only=True,
    args=(
        Arg("src",
            "Source path. Prefix ./ for local files; bare names are drive paths.",
            required=True, type="path"),
        Arg("dest",
            "Destination path. ./ for local; bare names are drive paths.",
            required=True, type="path"),
    ),
))
