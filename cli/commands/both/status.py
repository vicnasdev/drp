"""
cli/commands/both/status.py
"""
from __future__ import annotations
import argparse
from cli.base import BaseCommand, AuthCommand
from cli.api import APIClient, files as files_api, auth as auth_api


class StatusCommand(AuthCommand):
    name        = "status"
    description = "Show account info or drop metadata"

    def run(self, args: list[str]) -> int:
        self.require_auth()
        opts   = _parse_status(args)
        client = APIClient.from_config(self.config, authed=True)

        if opts.key:
            meta = files_api.fetch(client, opts.key)
            rows = [
                ("key",        meta.get("key", "")),
                ("filename",   meta.get("filename", "")),
                ("size",       meta.get("size_display", "")),
                ("type",       meta.get("content_type", "")),
                ("expires",    meta.get("expires_at", "∞")),
                ("public",     str(meta.get("is_public", False))),
                ("encrypted",  str(meta.get("is_encrypted", False))),
                ("burn",       str(meta.get("burn_after_read", False))),
                ("views",      str(meta.get("view_count", 0))),
                ("created",    meta.get("created_at", "")),
            ]
        else:
            me   = auth_api.whoami(client)
            rows = [
                ("user",      me.get("username", "")),
                ("plan",      me.get("plan", "")),
                ("storage",   f"{me.get('storage_used_display','')} / {me.get('storage_quota_display','')}"),
                ("drops",     str(me.get("drop_count", 0))),
                ("folders",   str(me.get("folder_count", 0))),
                ("server",    self.server_url),
            ]

        width = max(len(k) for k, _ in rows)
        for label, value in rows:
            self.out(f"  {label.ljust(width)}  {value}")
        return 0


def _parse_status(args):
    p = argparse.ArgumentParser(prog="status", add_help=False)
    p.add_argument("key", nargs="?", default=None)
    return p.parse_args(args)