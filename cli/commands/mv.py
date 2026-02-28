"""
cli/commands/shell/mv.py

Move files within drp or from drp to real FS.

  mv file.txt newname.txt   — rename within drp (same key, same expiry)
  mv file.txt subdir/       — move into drp subfolder (same key)
  mv file.txt ../           — download to real FS then delete from drp
"""
from __future__ import annotations

import os
from pathlib import Path
from cli.base import SpinnerCommand, AuthCommand
from cli.api import APIClient, files as files_api, folders as folders_api
from cli import cache


def _is_real(path: str) -> bool:
    return path.startswith("../") or path.startswith("./") or path.startswith("/") \
           or path == ".."


def _resolve_real_path(target: str, launch_dir: Path) -> Path | None:
    """Resolve a real-FS path (starting with ../, ./, /) from the launch dir."""
    if target.startswith("../") or target == "..":
        rest = target
        levels = 0
        while rest.startswith("../"):
            levels += 1
            rest = rest[3:]
        if rest == "..":
            levels += 1
            rest = ""
        base = launch_dir
        for _ in range(levels - 1):
            base = base.parent
        return (base / rest).resolve() if rest else base.resolve()
    elif target.startswith("./"):
        return (launch_dir / target[2:]).resolve()
    elif target.startswith("/"):
        return Path(target).resolve()
    return None


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

        src_real  = _is_real(src)
        dest_real = _is_real(dest)

        if src_real and not dest_real:
            # real FS → drp: upload into current/dest folder, then delete local file
            return self._move_from_real(client, src, dest)
        elif not src_real and dest_real:
            return self._move_to_real(client, src, dest)
        else:
            return self._move_within_drp(client, src, dest)

    # ---------------------------------------------------------------- real FS → drp

    def _move_from_real(self, client, src: str, dest: str) -> int:
        """Upload a real file into the current (or named) drp folder, then delete local."""
        import mimetypes
        from pathlib import Path as _Path

        # Resolve real FS path using same logic as up.py
        launch_dir = _Path(os.getcwd()) if hasattr(self, '_launch_dir') else _Path(__import__('os').getcwd())
        p = _resolve_real_path(src, launch_dir)

        if not p or not p.exists():
            self.err(f"not found on filesystem: {src}")
            return 1
        if not p.is_file():
            self.err(f"not a file: {src}")
            return 1

        filename     = p.name
        content_type = mimetypes.guess_type(str(p))[0] or "application/octet-stream"

        # Destination folder
        if dest in (".", "./"):
            folder_id = self.config.get("shell", {}).get("cwd_id")
        elif dest.endswith("/") and not _is_real(dest):
            folder_id = self._slug_to_folder_id(client, dest.strip("/"))
        else:
            folder_id = self.config.get("shell", {}).get("cwd_id")

        with self.spin(f"Uploading {filename}"):
            with open(p, "rb") as fobj:
                result = files_api.upload(
                    client, fobj, filename, content_type,
                    folder_id=folder_id,
                )

        cache.add({
            "key":      result["key"],
            "filename": filename,
            "size":     str(p.stat().st_size),
            "exp":      result.get("expires_at", ""),
            "owner":    "",
        })

        # Delete local file after successful upload
        try:
            p.unlink()
        except Exception as e:
            self.warn(f"uploaded but could not delete local file: {e}")

        self.success(f"moved {src} → drp/{result['key']}")
        return 0

    def _slug_to_folder_id(self, client, slug: str):
        try:
            folder_id = self.config.get("shell", {}).get("cwd_id")
            data = folders_api.list_contents(client, folder_id) if folder_id \
                   else folders_api.list_root(client)
            match = next((f for f in data.get("folders", []) if f["slug"] == slug), None)
            return match["id"] if match else None
        except Exception:
            return None

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
