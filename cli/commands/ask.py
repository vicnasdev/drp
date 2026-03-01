"""ask — Ask the drp help bot a question."""

from . import Arg, Command, register

cmd = register(Command(
    name="ask",
    description="Ask the drp help bot a question.",
    args=(
        Arg("question",
            "Your question, in quotes.",
            required=True),
    ),
))
