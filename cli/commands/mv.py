"""
cli/commands/shell/mv.py

Move files within drp or from drp to real FS.

  mv file.txt newname.txt   — rename within drp (same key, same expiry)
  mv file.txt subdir/       — move into drp subfolder (same key)
  mv file.txt ../           — download to real FS then delete from drp
"""
from __future__ import annotations

from pathlib import Path
from cli.base import SpinnerCommand, AuthCommand
from cli.api import APIClient, files as files_api, folders as folders_api
from cli import cache


def _is_real(path: str) -> bool:
    return path.startswith("../") or path.startswith("./") or path.startswith("/") \
           or path in ("..", ".")


class MvCommand(SpinnerCommand, AuthCommand):
    name        = "mv"
    description = "Move or rename a file within drp, or download-and-delete to real FS"

    def run(self, args: list[str]) -> int:
        self.require_auth()
        if len(args) < 2:
            self.err("usage: mv <src> <dest>")
            return 1

        src, dest = args[0], args[1]
        client    = APIClient.from_config(self.config, authed=True)

        if _is_real(dest):
            return self._move_to_real(client, src, dest)
        else:
            return self._move_within_drp(client, src, dest)

    # ---------------------------------------------------------------- drp → real FS

    def _move_to_real(self, client, src: str, dest: str) -> int:
        key = self._filename_to_key(client, src)
        if key is None:
            self.err(f"not found in drp: {src}")
            return 1

        with self.spin("Fetching"):
            meta = files_api.fetch(client, key)
            raw  = files_api.fetch_content(client, key)

        dest_path = Path(dest)
        if dest_path.is_dir() or dest.endswith("/"):
            dest_path = dest_path / meta.get("filename", src)

        dest_path.write_bytes(raw)

        with self.spin("Deleting from drp"):
            files_api.delete(client, key)
            cache.remove(key)

        self.success(f"moved {src} → {dest_path}")
        return 0

    # ---------------------------------------------------------------- within drp

    def _move_within_drp(self, client, src: str, dest: str) -> int:
        key = self._filename_to_key(client, src)
        if key is None:
            self.err(f"not found in drp: {src}")
            return 1

        dest_is_dir = dest.endswith("/")

        if dest_is_dir:
            # Move into a subfolder — update folder membership
            slug = dest.strip("/")
            folder_id = self.config.get("shell", {}).get("cwd_id")
            data  = folders_api.list_contents(client, folder_id) if folder_id \
                    else folders_api.list_root(client)
            match = next((f for f in data.get("folders", []) if f["slug"] == slug), None)
            if not match:
                self.err(f"folder not found: {dest}")
                return 1
            with self.spin("Moving"):
                # Remove from current folder, add to dest folder
                # (update FolderItem via patch on the file metadata)
                files_api.update_meta(client, key, folder_id=match["id"])
        else:
            # Rename — same key, just update the filename metadata
            with self.spin("Renaming"):
                files_api.update_meta(client, key, filename=dest)
            # Update cache
            entry = cache.get(key)
            if entry:
                entry["filename"] = dest
                cache.add(entry)

        self.success(f"moved {src} → {dest}")
        return 0

    # ---------------------------------------------------------------- helpers

    def _filename_to_key(self, client, filename: str) -> str | None:
        try:
            folder_id = self.config.get("shell", {}).get("cwd_id")
            data = folders_api.list_contents(client, folder_id) if folder_id \
                   else folders_api.list_root(client)
            for item in data.get("items", []):
                label = item.get("filename") or item.get("label") or ""
                if label.lower() == filename.lower():
                    return item["key"]
        except Exception:
            pass
        return None
