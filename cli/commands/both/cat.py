"""
cli/commands/both/cat.py

Display a drop's content with syntax highlighting.
Auto-bookmarks if you don't own it.
--parse / --field for structured extraction (JSON, CSV).

Inside shell:   cat myfile.txt          # resolved by filename/path against CWD
                cat -k MfZDdyb0         # explicit key, bypasses path resolution
Outside shell:  drp cat -k MfZDdyb0    # explicit key required (no CWD to resolve against)
"""
from __future__ import annotations
import argparse
import csv
import io
import json
from cli.base import SpinnerCommand
from cli.base.crypto import decrypt, prompt_passphrase
from cli.api import APIClient, files as files_api
from cli import cache


class CatCommand(SpinnerCommand):
    name        = "cat"
    description = "Display a drop's content with syntax highlighting"

    def run(self, args: list[str]) -> int:
        p = argparse.ArgumentParser(prog="cat", add_help=False)
        # ref is now optional — you can use -k/--key instead
        p.add_argument("ref",           nargs="?", default=None,
                       help="Filename or path (inside shell) to look up")
        p.add_argument("-k", "--key",   default=None, metavar="KEY",
                       help="Fetch directly by drop key, bypassing path resolution")
        p.add_argument("--decrypt",     default=None, metavar="PASSPHRASE")
        p.add_argument("--parse",       action="store_true")
        p.add_argument("--field",       default=None)
        opts = p.parse_args(args)

        # --key takes priority; fall back to positional ref
        if opts.key:
            ref = opts.key
        elif opts.ref:
            ref = opts.ref
        else:
            # outside shell there's no CWD to resolve paths against, so a key is required
            if not self.in_shell:
                self.err("usage: drp cat -k <key>")
                return 1
            self.err("usage: cat <filename>  or  cat -k <key>")
            return 1

        client = APIClient.from_config(self.config, authed=bool(
            self.config.get("auth", {}).get("token")
        ))

        with self.spin("Fetching"):
            meta = files_api.fetch(client, ref)
            raw  = files_api.fetch_content(client, ref)

        if meta.get("is_encrypted"):
            passphrase = opts.decrypt or prompt_passphrase()
            raw        = decrypt(raw, passphrase)

        content = raw.decode("utf-8", errors="replace")

        if opts.parse:
            return _print_parsed(self, content, opts.field)

        self.print_content(content, filename=meta.get("filename"))

        # auto-bookmark if not owned
        me = self.config.get("auth", {}).get("username", "")
        if meta.get("owner") != me and me:
            cache.add({
                "key":      ref,
                "filename": meta.get("filename", ref),
                "size":     meta.get("size_display", ""),
                "exp":      meta.get("expires_at", ""),
                "owner":    meta.get("owner", ""),
            })

        return 0


def _print_parsed(cmd, content: str, field: str | None) -> int:
    try:
        data = json.loads(content)
        if field:
            cmd.out(str(data.get(field, "")))
        else:
            cmd.out(json.dumps(data, indent=2))
        return 0
    except json.JSONDecodeError:
        pass
    try:
        rows = list(csv.DictReader(io.StringIO(content)))
        if field:
            for r in rows:
                cmd.out(r.get(field, ""))
        else:
            cmd.print_table(rows, list(rows[0].keys()) if rows else [])
        return 0
    except Exception:
        cmd.err("--parse: unsupported format (JSON and CSV supported)")
        return 1