"""
cli/commands/both/ls.py

List drops.

Outside shell — reads local cache. Instant, offline, no network.
Inside shell  — fetches live folder contents from server.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

from cli.base import SpinnerCommand, AuthCommand
from cli.api import APIClient, folders as folders_api
from cli import cache as cache_store


class LsCommand(SpinnerCommand, AuthCommand):
    name        = "ls"
    description = "List your drops"

    def run(self, args: list[str]) -> int:
        self.require_auth()
        opts = _parse(args)
        return self._shell_ls(opts) if self.in_shell else self._cache_ls(opts)

    # ---------------------------------------------------------------- outside shell: cache

    def _cache_ls(self, opts) -> int:
        entries = cache_store.all_entries()
        if not entries:
            self.dim("no cached drops — run: drp up <file>")
            return 0

        rows = []
        for e in entries:
            exp_raw = e.get("exp", "")
            exp     = _fmt_exp(exp_raw)
            rows.append({
                "filename": e.get("filename", ""),
                "preview":  e.get("preview", ""),
                "owner":    f"→ {e['owner']}" if e.get("owner") else "",
                "size":     e.get("size", ""),
                "exp":      exp,
                "key":      e.get("key", ""),
            })

        if opts.export:
            print(json.dumps(rows, indent=2))
            return 0

        self.print_drop_table(rows)
        return 0

    # ---------------------------------------------------------------- inside shell: live

    def _shell_ls(self, opts) -> int:
        client    = APIClient.from_config(self.config, authed=True)
        cwd       = self.config.get("shell", {}).get("cwd", "/")
        folder_id = self.config.get("shell", {}).get("cwd_id")

        with self.spin("Loading"):
            if folder_id:
                data = folders_api.list_contents(client, folder_id)
            else:
                data = folders_api.list_root(client)

        items   = data.get("items", [])
        folders = data.get("folders", [])
        rows    = []

        for f in folders:
            rows.append({
                "filename": f"📁 {f['slug']}/",
                "preview":  "",
                "owner":    "",
                "size":     "",
                "exp":      "",
                "key":      "",
            })

        for item in items:
            rows.append({
                "filename": item.get("filename", item.get("key", "")),
                "preview":  item.get("preview", ""),
                "owner":    f"→ {item['owner']}" if item.get("owner") else "",
                "size":     item.get("size_display", ""),
                "exp":      _fmt_exp(item.get("expires_at", "")),
                "key":      item.get("key", ""),
            })

        if not rows:
            self.dim("(empty)")
            return 0

        if opts.export:
            print(json.dumps(rows, indent=2))
            return 0

        self.print_drop_table(rows)
        return 0


# ------------------------------------------------------------------ helpers

def _fmt_exp(raw: str) -> str:
    if not raw:
        return "∞"
    try:
        dt    = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        delta = dt - datetime.now(timezone.utc)
        secs  = int(delta.total_seconds())
        if secs < 0:
            return "expired"
        if secs < 3600:
            return f"{secs // 60}m"
        if secs < 86400:
            return f"{secs // 3600}h"
        return f"{secs // 86400}d"
    except Exception:
        return raw


def _parse(args):
    p = argparse.ArgumentParser(prog="ls", add_help=False)
    p.add_argument("folder", nargs="?", default=None)
    p.add_argument("-l",          action="store_true")
    p.add_argument("-r",          action="store_true")
    p.add_argument("--export",    action="store_true")
    return p.parse_args(args)
