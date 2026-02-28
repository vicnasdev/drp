"""
cli/commands/both/get.py

Download a drop to disk, fork it, or claim a folder share URL.
No display, no highlighting — that's cat's job.

  drp get xK9mZ2                    # download, keeps original filename
  drp get xK9mZ2 --name report.md   # download with custom name
  drp get xK9mZ2 --fork             # fork as your own copy
  drp get https://drp.fyi/@alice/docs/?t=abc123   # claim folder share
"""
from __future__ import annotations

import argparse
from pathlib import Path
from urllib.parse import urlparse

from cli.base import SpinnerCommand
from cli.api import APIClient, files as files_api
from cli import cache


class GetCommand(SpinnerCommand):
    name        = "get"
    description = "Download a drop to disk"

    def run(self, args: list[str]) -> int:
        opts   = _parse(args)
        client = APIClient.from_config(self.config, authed=bool(
            self.config.get("auth", {}).get("token")
        ))

        if _is_share_url(opts.ref, self.server_url):
            return self._claim_share(client, opts.ref)

        if opts.fork:
            return self._fork(client, opts)

        return self._download(client, opts)

    # ---------------------------------------------------------------- download

    def _download(self, client, opts) -> int:
        key = _resolve_key(opts.ref)
        with self.spin("Downloading"):
            meta = files_api.fetch(client, key)
            raw  = files_api.fetch_content(client, key)
        filename = opts.name or meta.get("filename", key)
        Path(filename).write_bytes(raw)
        self.success(f"saved {filename} ({len(raw)} bytes)")
        return 0

    # ---------------------------------------------------------------- fork

    def _fork(self, client, opts) -> int:
        key = _resolve_key(opts.ref)
        with self.spin("Forking"):
            result = files_api.fork(client, key)
        cache.add({
            "key":      result["key"],
            "filename": result.get("filename", key),
            "size":     result.get("size_display", ""),
            "exp":      result.get("expires_at", ""),
            "owner":    "",
        })
        self.success("forked — you now own a copy")
        self.print_key(result["key"], self.server_url)
        return 0

    # ---------------------------------------------------------------- share URL

    def _claim_share(self, client, url: str) -> int:
        with self.spin("Claiming folder share"):
            from cli.api import folders as folders_api
            result = folders_api.resolve_path(client, url)
        self.success(f"folder bookmarked — open shell and: cd {result.get('path', '')}")
        return 0


# ------------------------------------------------------------------ helpers

def _is_share_url(ref: str, server_url: str) -> bool:
    try:
        parsed = urlparse(ref)
        base   = urlparse(server_url)
        return parsed.netloc == base.netloc and "t=" in (parsed.query or "")
    except Exception:
        return False


def _resolve_key(ref: str) -> str:
    ref = ref.strip("/")
    return ref.split("/")[-1] if "/" in ref else ref


def _parse(args):
    p = argparse.ArgumentParser(prog="get", add_help=False)
    p.add_argument("ref")
    p.add_argument("-n", "--name", default=None, help="Save with this filename")
    p.add_argument("--fork",       action="store_true")
    return p.parse_args(args)
