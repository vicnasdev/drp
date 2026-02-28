"""
cli/commands/shell/cd.py
"""
from __future__ import annotations
from cli.base import BaseCommand
from cli.api import APIClient, folders as folders_api


class CdCommand(BaseCommand):
    name        = "cd"
    description = "Navigate the folder tree"

    def run(self, args: list[str]) -> int:
        if not args:
            # cd with no args → go to root
            self.config.setdefault("shell", {})["cwd"]    = "/"
            self.config["shell"]["cwd_id"] = None
            return 0

        path   = args[0]
        client = APIClient.from_config(self.config, authed=True)
        result = folders_api.resolve_path(client, _resolve(path, self.config))

        if result.get("type") != "folder":
            self.err(f"not a folder: {path}")
            return 1

        shell = self.config.setdefault("shell", {})
        shell["cwd"]    = result["path"]
        shell["cwd_id"] = result["object"]["id"]
        return 0


def _resolve(path: str, config: dict) -> str:
    cwd = config.get("shell", {}).get("cwd", "/")
    if path.startswith("/") or path.startswith("@"):
        return path
    if path == "..":
        parts = cwd.rstrip("/").rsplit("/", 1)
        return parts[0] or "/"
    return cwd.rstrip("/") + "/" + path
