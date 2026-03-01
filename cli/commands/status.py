"""status — Display account info."""

from . import Command, register

cmd = register(Command(
    name="status",
    description="Display account info: username, plan, storage, file count, folder count.",
))
