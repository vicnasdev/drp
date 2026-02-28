"""
cli/commands/shell/getkey.py
"""
from __future__ import annotations
from cli.base import BaseCommand
from cli.api import APIClient, files as files_api


class GetkeyCommand(BaseCommand):
    name        = "getkey"
    description = "Show the key and URL for a file"

    def run(self, args: list[str]) -> int:
        if not args:
            self.err("usage: getkey <file>")
            return 1
        client = APIClient.from_config(self.config, authed=bool(self.config.get("auth", {}).get("token")))
        meta   = files_api.fetch(client, args[0])
        self.print_key(meta["key"], self.server_url)
        return 0
