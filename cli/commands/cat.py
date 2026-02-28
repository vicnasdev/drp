"""
cli/commands/both/cat.py

Display a drop's content with syntax highlighting.
Auto-bookmarks if you don't own it.
--parse / --field for structured extraction (JSON, CSV).

Inside shell:   cat file3.json              # resolved by filename in current folder
                cat file3.json --field key  # auto-parses, extracts field
                cat -k OmL3nsn9            # explicit key
Outside shell:  drp cat -k OmL3nsn9
                drp cat -k OmL3nsn9 --parse --field key
"""
from __future__ import annotations
import argparse
import csv
import io
import json
from cli.base import SpinnerCommand
from cli.base.crypto import decrypt, prompt_passphrase
from cli.api import APIClient, files as files_api, folders as folders_api
from cli import cache


class CatCommand(SpinnerCommand):
    name        = "cat"
    description = "Display a drop's content with syntax highlighting"

    def run(self, args: list[str]) -> int:
        p = argparse.ArgumentParser(prog="cat", add_help=False)
        p.add_argument("ref",         nargs="?", default=None,
                       help="Filename in current folder (shell only)")
        p.add_argument("-k", "--key", default=None, metavar="KEY",
                       help="Drop key — works everywhere")
        p.add_argument("--decrypt",   default=None, metavar="PASSPHRASE")
        p.add_argument("--parse",     action="store_true")
        p.add_argument("--field",     default=None)
        opts = p.parse_args(args)

        # FIX: --field implies --parse — no reason to require both flags
        if opts.field:
            opts.parse = True

        client = APIClient.from_config(self.config, authed=bool(
            self.config.get("auth", {}).get("token")
        ))

        if opts.key:
            key = opts.key
        elif opts.ref and self.in_shell:
            key = self._resolve_filename(client, opts.ref)
            if key is None:
                self.err(f"no drop named '{opts.ref}' in current folder")
                return 1
        elif opts.ref and not self.in_shell:
            self.err("outside the shell use:  drp cat -k <key>")
            return 1
        else:
            self.err("usage: cat <filename>  or  cat -k <key>" if self.in_shell
                     else "usage: drp cat -k <key>")
            return 1

        with self.spin("Fetching"):
            meta = files_api.fetch(client, key)
            raw  = files_api.fetch_content(client, key)

        if meta.get("is_encrypted"):
            passphrase = opts.decrypt or prompt_passphrase()
            raw        = decrypt(raw, passphrase)

        content = raw.decode("utf-8", errors="replace")

        if opts.parse:
            return _print_parsed(self, content, opts.field)

        self.print_content(content, filename=meta.get("filename"))

        me = self.config.get("auth", {}).get("username", "")
        if meta.get("owner") != me and me:
            cache.add({
                "key":      key,
                "filename": meta.get("filename", key),
                "size":     meta.get("size_display", ""),
                "exp":      meta.get("expires_at", ""),
                "owner":    meta.get("owner", ""),
            })

        return 0

    def _resolve_filename(self, client, filename: str) -> str | None:
        try:
            folder_id = self.config.get("shell", {}).get("cwd_id")
            if folder_id:
                data = folders_api.list_contents(client, folder_id)
            else:
                data = folders_api.list_root(client)
            for item in data.get("items", []):
                label = item.get("filename") or item.get("label") or ""
                if label.lower() == filename.lower():
                    return item["key"]
        except Exception:
            pass
        # fallback: treat short refs as keys directly
        return filename if len(filename) <= 12 else None


def _print_parsed(cmd, content: str, field: str | None) -> int:
    # Try JSON first
    try:
        data = json.loads(content)
        if field:
            if field not in data:
                cmd.err(f"--field: key '{field}' not found in JSON object")
                return 1
            cmd.out(str(data[field]))
        else:
            cmd.out(json.dumps(data, indent=2))
        return 0
    except json.JSONDecodeError:
        pass

    # Try CSV
    try:
        rows = list(csv.DictReader(io.StringIO(content)))
        if not rows:
            cmd.err("--parse: file is empty or not valid JSON/CSV")
            return 1
        if field:
            found = False
            for r in rows:
                # Case-insensitive field match
                match = next((v for k, v in r.items() if k.lower() == field.lower()), None)
                if match is not None:
                    cmd.out(match)
                    found = True
            if not found:
                cmd.err(f"--field: column '{field}' not found. Available: {', '.join(rows[0].keys())}")
                return 1
        else:
            cmd.print_table(rows, list(rows[0].keys()))
        return 0
    except Exception:
        pass

    cmd.err("--parse: unsupported format (JSON and CSV supported)")
    return 1