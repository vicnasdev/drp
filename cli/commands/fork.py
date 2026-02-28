"""
cli/commands/shell/fork.py
"""
from __future__ import annotations
import argparse
from cli.base import SpinnerCommand, AuthCommand
from cli.api import APIClient, files as files_api
from cli import cache


class ForkCommand(SpinnerCommand, AuthCommand):
    name        = "fork"
    description = "Fork a drop as your own independent copy"

    def run(self, args: list[str]) -> int:
        self.require_auth()
        p = argparse.ArgumentParser(prog="fork", add_help=False)
        p.add_argument("ref")
        p.add_argument("-k", "--key", default=None)
        opts   = p.parse_args(args)
        client = APIClient.from_config(self.config, authed=True)

        with self.spin("Forking"):
            result = files_api.fork(client, opts.ref, new_key=opts.key)

        cache.add({
            "key":      result["key"],
            "filename": result.get("filename", opts.ref),
            "size":     result.get("size_display", ""),
            "exp":      result.get("expires_at", ""),
            "owner":    "",
        })
        self.success("forked — you now own a copy")
        self.print_key(result["key"], self.server_url)
        return 0
