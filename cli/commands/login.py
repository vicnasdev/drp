"""login — Authenticate interactively."""

from . import Command, register

cmd = register(Command(
    name="login",
    description="Authenticate interactively. Prompts for username and password.",
))
