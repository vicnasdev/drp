"""
cli/commands/both/ask.py

Help bot. History synced server-side per user (session-only for anon).

  drp ask "how do I share a folder?"
"""
from __future__ import annotations
from cli.base import SpinnerCommand
from cli.api import APIClient
from cli.base.errors import parse_response


class AskCommand(SpinnerCommand):
    name        = "ask"
    description = "Ask the drp help bot a question"

    def run(self, args: list[str]) -> int:
        if not args:
            self.err("usage: ask \"<question>\"")
            return 1

        question = " ".join(args).strip('"\'')
        client   = APIClient.from_config(self.config, authed=bool(
            self.config.get("auth", {}).get("token")
        ))

        with self.spin("Thinking"):
            resp   = client.post("/api/v1/helpbot/", json={"question": question})
            result = parse_response(resp)

        answer = result.get("answer", "")
        self.out()
        self.print_content(answer, lexer="markdown")
        self.out()
        return 0
