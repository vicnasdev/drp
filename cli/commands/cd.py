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
            self.config.setdefault("shell", {})["cwd"]    = "/"
            self.config["shell"]["cwd_id"] = None
            return 0

        path   = args[0].rstrip("/")
        client = APIClient.from_config(self.config, authed=True)

        resolved = _resolve(path, self.config)
        result   = folders_api.resolve_path(client, resolved)

        if result.get("type") != "folder":
            self.err(f"not a folder: {path}")
            return 1

        shell = self.config.setdefault("shell", {})
        # Use server-provided path if available, otherwise derive from local resolution.
        # FIX: original used result["path"] which the server never returned → KeyError.
        # Server now returns "path"; we also fall back locally for safety.
        shell["cwd"]    = result.get("path") or ("/" + resolved.split("/", 1)[-1].lstrip("/") if "/" in resolved else "/")
        shell["cwd_id"] = result["object"].get("id")  # None at root
        return 0


def _resolve(path: str, config: dict) -> str:
    """
    Build a fully-qualified @username/slug/... path for the resolve API.

    FIX: the original built paths like '/example' which the server's resolve()
    rejected with 400 "invalid path" — it expects '@username/slug' format.
    We now always prepend @username.
    """
    username = config.get("auth", {}).get("username", "")
    cwd      = config.get("shell", {}).get("cwd", "/").strip("/")

    if path.startswith("@"):
        return path

    if path == "..":
        parts = cwd.rsplit("/", 1)
        parent = parts[0] if len(parts) > 1 else ""
        return f"@{username}/{parent}".rstrip("/") if parent else f"@{username}"

    base = f"@{username}/{cwd}".rstrip("/") if cwd else f"@{username}"
    return f"{base}/{path}"
