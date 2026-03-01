"""ping — Check connectivity and print round-trip latency."""

from . import Command, register

cmd = register(Command(
    name="ping",
    description="Check connectivity to the server and print round-trip latency.",
))
