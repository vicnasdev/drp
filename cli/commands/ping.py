"""ping — Check connectivity and print round-trip latency."""

from . import Command, register
from cli.utils import spin

def run(args):
    print("Soon.")

cmd = register(Command(
    name="ping",
    description="Check connectivity to the server and print round-trip latency.",
    run=spin(run, "Ping")
))
