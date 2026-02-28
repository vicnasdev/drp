"""
cli/commands/both/token.py

Account-level API token management.

  drp token create [--label "ci"]
  drp token list
  drp token revoke <id>
"""
from __future__ import annotations
import argparse
from cli.base import BaseCommand, AuthCommand
from cli.api import APIClient, tokens as tokens_api


class TokenCommand(AuthCommand):
    name        = "token"
    description = "Manage API tokens (create / list / revoke)"

    def run(self, args: list[str]) -> int:
        self.require_auth()
        if not args:
            self.err("usage: token <create|list|revoke>")
            return 1

        sub    = args[0]
        rest   = args[1:]
        client = APIClient.from_config(self.config, authed=True)

        match sub:
            case "create": return self._create(client, rest)
            case "list":   return self._list(client)
            case "revoke": return self._revoke(client, rest)
            case _:
                self.err(f"unknown subcommand: {sub}")
                return 1

    def _create(self, client, args) -> int:
        p     = argparse.ArgumentParser(prog="token create", add_help=False)
        p.add_argument("--label", default="")
        opts  = p.parse_args(args)
        result = tokens_api.create(client, label=opts.label)
        self.success("API token created — save this, it won't be shown again:")
        self.out(f"  {result['token']}")
        if opts.label:
            self.dim(f"  label: {opts.label}")
        return 0

    def _list(self, client) -> int:
        items = tokens_api.list_all(client)
        if not items:
            self.dim("no API tokens — run: token create")
            return 0
        self.print_table(items, ["id", "label", "last_used", "created_at"])
        return 0

    def _revoke(self, client, args) -> int:
        if not args:
            self.err("usage: token revoke <id>")
            return 1
        tokens_api.revoke(client, int(args[0]))
        self.success("token revoked")
        return 0
