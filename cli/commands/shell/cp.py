"""
cli/commands/shell/cp.py

Copy a drop. Without --fork: local download. With --fork: new owned copy in drp.
Works across folder boundaries and with absolute paths.
"""
from __future__ import annotations
import argparse
from pathlib import Path
from cli.base import SpinnerCommand, AuthCommand
from cli.api import APIClient, files as files_api
from cli import cache


class CpCommand(SpinnerCommand, AuthCommand):
    name        = "cp"
    description = "Copy a drop locally or fork as new owned drop"

    def run(self, args: list[str]) -> int:
        self.require_auth()
        p = argparse.ArgumentParser(prog="cp", add_help=False)
        p.add_argument("src")
        p.add_argument("dest")
        p.add_argument("--fork", action="store_true")
        opts   = p.parse_args(args)
        client = APIClient.from_config(self.config, authed=True)

        with self.spin("Fetching"):
            meta = files_api.fetch(client, opts.src)

        if opts.fork:
            with self.spin("Forking"):
                result = files_api.fork(client, opts.src)
            cache.add({
                "key":      result["key"],
                "filename": result.get("filename", opts.src),
                "size":     result.get("size_display", ""),
                "exp":      result.get("expires_at", ""),
                "owner":    "",
            })
            self.success("forked — you now own a copy")
            self.print_key(result["key"], self.server_url)
        else:
            dest = Path(opts.dest)
            if dest.is_dir():
                dest = dest / meta.get("filename", opts.src)
            with self.spin(f"Downloading → {dest}"):
                raw = files_api.fetch_content(client, opts.src)
            dest.write_bytes(raw)
            self.success(f"saved to {dest}")

        return 0
