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

        # FIX: the original passed opts.ref straight to resolve_path() which
        # expects @username/slug format. Plain filenames like "file1.txt" or
        # folder names like "example" produced "invalid path" 400 errors.
        # We now:
        #   1. Check if ref looks like a folder name → resolve via @username/slug
        #   2. Otherwise treat as a filename → look up key in current folder
        ref = opts.ref.rstrip("/")
        is_folder_ref = opts.ref.endswith("/") or opts.ref.startswith("@")

        if is_folder_ref or self._is_folder(client, ref):
            return self._rm_folder(client, opts, ref)
        else:
            return self._rm_file(client, opts, ref)

    def _is_folder(self, client, ref: str) -> bool:
        """Check if ref matches a subfolder slug in the current folder."""
        try:
            folder_id = self.config.get("shell", {}).get("cwd_id")
            if folder_id:
                data = folders_api.list_contents(client, folder_id)
            else:
                data = folders_api.list_root(client)
            return any(f.get("slug") == ref for f in data.get("folders", []))
        except Exception:
            return False

    def _rm_folder(self, client, opts, ref: str) -> int:
        username = self.config.get("auth", {}).get("username", "")
        cwd      = self.config.get("shell", {}).get("cwd", "/").strip("/")
        base     = f"@{username}/{cwd}".rstrip("/") if cwd else f"@{username}"
        full_path = f"{base}/{ref}" if not ref.startswith("@") else ref

        with self.spin("Resolving"):
            obj = folders_api.resolve_path(client, full_path)

        if obj.get("type") != "folder":
            self.err(f"not a folder: {ref}")
            return 1

        if not opts.f:
            if not self.confirm(f"delete folder '{ref}'?"):
                self.abort()

        with self.spin("Deleting"):
            folders_api.delete(client, obj["object"]["id"], recursive=opts.recursive)

        self.success(f"deleted {ref}")
        return 0

    def _rm_file(self, client, opts, ref: str) -> int:
        # Resolve filename → key from current folder's item list
        key = self._filename_to_key(client, ref)
        if key is None:
            self.err(f"no drop named '{ref}' in current folder")
            return 1

        if not opts.f:
            if not self.confirm(f"delete '{ref}'?"):
                self.abort()

        with self.spin("Deleting"):
            files_api.delete(client, key)
            cache.remove(key)

        self.success(f"deleted {ref}")
        return 0

    def _filename_to_key(self, client, filename: str) -> str | None:
        """Resolve a filename to its drop key in the current folder."""
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
        return None
