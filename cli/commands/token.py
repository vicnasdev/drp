"""token — Manage account-level API tokens."""

from . import Arg, Command, register

cmd = register(Command(
    name="token",
    description="Manage account-level API tokens for scripts and integrations.",
    args=(
        Arg("action",
            "Subcommand: create, list, or revoke.",
            required=True, choices=("create", "list", "revoke")),
        Arg("target",
            "Token ID (for revoke)."),
        Arg("--label",
            "Human-readable label for a new token."),
    ),
))
