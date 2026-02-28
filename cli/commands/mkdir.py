"""
cli/commands/shell/mkdir.py
"""
from __future__ import annotations
import argparse
from cli.base import SpinnerCommand, AuthCommand
from cli.api import APIClient, folders as folders_api


class MkdirCommand(SpinnerCommand, AuthCommand):
    name        = "mkdir"
    description = "Create a folder"

    def run(self, args: list[str]) -> int:
        self.require_auth()
        p    = argparse.ArgumentParser(prog="mkdir", add_help=False)
        p.add_argument("name")
        p.add_argument("--public", action="store_true")
        opts = p.parse_args(args)

        client    = APIClient.from_config(self.config, authed=True)
        parent_id = self.config.get("shell", {}).get("cwd_id")

        with self.spin(f"Creating {opts.name}"):
            result = folders_api.create(client, opts.name, parent_id=parent_id, public=opts.public)

        self.success(f"created {opts.name}/")
        return 0
