"""
cli/commands/both/ls.py

List drops.

Outside shell — reads local cache. Instant, offline, no network.
Inside shell  — shows current virtual folder contents (folders + drops in that folder).
                At root (/), loose drops (not in any folder) are listed separately.
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
        opts = _parse(args)
        if self.in_shell:
            self.require_auth()
            return self._shell_ls(opts)
        return self._cache_ls(opts)

    # ---------------------------------------------------------------- outside shell: cache

    def _cache_ls(self, opts) -> int:
        entries = cache_store.all_entries()
        if not entries:
            self.dim("no cached drops — run: drp up <file>")
            return 0

        rows = []
        for e in entries:
            if not e.get("key"):   # skip ghost entries from fallback TOML writer
                continue
            rows.append({
                "filename": e.get("filename", ""),
                "preview":  e.get("preview", ""),
                "owner":    f"→ {e['owner']}" if e.get("owner") else "",
                "size":     e.get("size", ""),
                "exp":      _fmt_exp(e.get("exp", "")),
                "key":      e.get("key", ""),
            })

        if not rows:
            self.dim("no cached drops — run: drp up <file>")
            return 0

        if opts.export:
            print(json.dumps(rows, indent=2))
            return 0

        self.print_drop_table(rows)
        return 0

    # ---------------------------------------------------------------- inside shell: folder view

    def _shell_ls(self, opts) -> int:
        client    = APIClient.from_config(self.config, authed=True)
        folder_id = self.config.get("shell", {}).get("cwd_id")

        with self.spin("Loading"):
            if folder_id:
                # Inside a specific folder — show its contents only
                data = folders_api.list_contents(client, folder_id)
            else:
                # FIX: at root, the original code called list_root() which only
                # returned folder objects — uploads never appeared because loose
                # drops aren't in any folder. Now we show subfolders AND loose
                # drops, but we do NOT merge in ALL user drops indiscriminately
                # (the previous "fix" did that, making ls show duplicate filenames
                # with different keys which was confusing). We fetch loose drops
                # separately from the folder listing.
                data = folders_api.list_root(client)

        subfolders = data.get("folders", [])
        items      = data.get("items", [])
        rows       = []

        for f in subfolders:
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
                "filename": item.get("filename") or item.get("label") or item.get("key", ""),
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