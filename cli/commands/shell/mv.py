"""
cli/commands/shell/mv.py

Move or rename a file/folder. Does not touch the key.
"""
from __future__ import annotations
from cli.base import SpinnerCommand, AuthCommand
from cli.api import APIClient, folders as folders_api, files as files_api
from cli.base.errors import DrpError


class MvCommand(SpinnerCommand, AuthCommand):
    name        = "mv"
    description = "Move or rename a file or folder"

    def run(self, args: list[str]) -> int:
        self.require_auth()
        if len(args) < 2:
            self.err("usage: mv <src> <dest>")
            return 1

        src, dest  = args[0], args[1]
        client     = APIClient.from_config(self.config, authed=True)

        with self.spin("Resolving"):
            obj = folders_api.resolve_path(client, src)

        with self.spin("Moving"):
            if obj["type"] == "folder":
                folders_api.rename(client, obj["object"]["id"], dest.split("/")[-1])
            else:
                # update label in FolderItem (display name, not key)
                files_api.update_meta(client, obj["object"]["key"], filename=dest.split("/")[-1])

        self.success(f"moved {src} → {dest}")
        return 0
