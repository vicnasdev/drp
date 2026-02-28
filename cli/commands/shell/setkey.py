"""
cli/commands/shell/setkey.py

Change the key for a file you own. Resets the expiry clock.
"""
from __future__ import annotations
from cli.base import SpinnerCommand, AuthCommand
from cli.api import APIClient, files as files_api
from cli import cache


class SetkeyCommand(SpinnerCommand, AuthCommand):
    name        = "setkey"
    description = "Change the key for a file (resets expiry)"

    def run(self, args: list[str]) -> int:
        self.require_auth()
        if len(args) < 2:
            self.err("usage: setkey <file> <newkey>")
            return 1

        ref, new_key = args[0], args[1]
        client       = APIClient.from_config(self.config, authed=True)

        with self.spin(f"Setting key → {new_key}"):
            result = files_api.setkey(client, ref, new_key)

        cache.remove(ref)
        cache.add({
            "key":      result["key"],
            "filename": result.get("filename", ref),
            "size":     result.get("size_display", ""),
            "exp":      result.get("expires_at", ""),
            "owner":    "",
        })
        self.print_key(result["key"], self.server_url)
        return 0
