"""setup — First-time configuration wizard."""

from . import Command, register

cmd = register(Command(
    name="setup",
    description="First-time configuration wizard. Sets server URL and writes config.",
))
