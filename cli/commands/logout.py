"""logout — Revoke the current bearer token and clear local config."""

from . import Command, register

cmd = register(Command(
    name="logout",
    description="Revoke the current bearer token on the server and clear local config.",
))
