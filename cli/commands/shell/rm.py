"""
cli/commands/shell/rm.py
"""
from __future__ import annotations
import argparse
from cli.base import SpinnerCommand, AuthCommand
from cli.api import APIClient, files as files_api, folders as folders_api
from cli import cache


class RmCommand(SpinnerCommand, AuthCommand):
    name        = "rm"
    description = "Delete a drop or folder"

    def run(self, args: list[str]) -> int:
        self.require_auth()
        p = argparse.ArgumentParser(prog="rm", add_help=False)
        p.add_argument("ref")
        p.add_argument("-f",            action="store_true")
        p.add_argument("--recursive",   action="store_true")
        opts   = p.parse_args(args)
        client = APIClient.from_config(self.config, authed=True)

        with self.spin("Resolving"):
            obj = folders_api.resolve_path(client, opts.ref)

        if not opts.f:
            kind = obj["type"]
            if not self.confirm(f"delete {kind} '{opts.ref}'?"):
                self.abort()

        with self.spin("Deleting"):
            if obj["type"] == "folder":
                folders_api.delete(client, obj["object"]["id"], recursive=opts.recursive)
            else:
                key = obj["object"]["key"]
                files_api.delete(client, key)
                cache.remove(key)

        self.success(f"deleted {opts.ref}")
        return 0
