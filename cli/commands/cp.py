"""
cli/commands/shell/cp.py

Copy files between real FS and drp drive, or within drp.

  cp ../file.txt .          — upload from real FS into current drp folder
  cp ../file.txt subdir/    — upload into a drp subfolder
  cp file.txt ../           — download from drp to real FS
  cp file.txt other.txt     — copy within drp (new key, 24h default expiry)
  cp file.txt subdir/       — copy within drp into subfolder
"""
from __future__ import annotations

import argparse
import mimetypes
import sys
from pathlib import Path

from cli.base import SpinnerCommand, AuthCommand
from cli.api import APIClient, files as files_api, folders as folders_api
from cli import cache


def _fmt_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _is_real(path: str) -> bool:
    """True if the path refers to the real filesystem.

    "." alone always means the current drp virtual folder (like a shell `.`).
    Only "../" prefix, "./" prefix, "/" prefix, or bare ".." are real-FS paths.
    This lets `cp ../file.txt .` work: src is real FS, dest is current drp folder.
    Paths starting with "@" are always drp paths (e.g. @vicnas/).
    """
    if path.startswith("@"):
        return False
    return path.startswith("../") or path.startswith("./") or path.startswith("/") \
           or path == ".."


def _is_drp_dir(path: str) -> bool:
    return path.endswith("/") or path in (".", "..")


class CpCommand(SpinnerCommand, AuthCommand):
    name        = "cp"
    description = "Copy files to/from/within the drp drive"

    def run(self, args: list[str]) -> int:
        self.require_auth()
        p = argparse.ArgumentParser(prog="cp", add_help=False)
        p.add_argument("src")
        p.add_argument("dest")
        opts   = p.parse_args(args)
        client = APIClient.from_config(self.config, authed=True)

        src_real  = _is_real(opts.src)
        dest_real = _is_real(opts.dest)

        # cp only makes sense inside the shell — outside the shell there is no
        # virtual CWD to anchor relative drp paths against, so drp→drp copies
        # silently target the wrong folder.  Direct the user to `drp up` instead.
        if not self.in_shell and not src_real and not dest_real:
            self.err(
                "cp between drp paths requires the shell.\n"
                "  Use: drp up <file>  to upload from the filesystem."
            )
            return 1

        if src_real and not dest_real:
            return self._upload(client, opts.src, opts.dest)
        elif not src_real and dest_real:
            return self._download(client, opts.src, opts.dest)
        elif not src_real and not dest_real:
            return self._drp_copy(client, opts.src, opts.dest)
        else:
            self.err("use a real cp/mv command to copy between real FS locations")
            return 1

    # ---------------------------------------------------------------- upload (real → drp)

    def _upload(self, client, src: str, dest: str) -> int:
        import os as _os
        launch_dir = Path(self.config.get("shell", {}).get("launch_dir", _os.getcwd()))

        # Resolve src relative to launch_dir (mirrors up.py logic)
        if src.startswith("../") or src == "..":
            rest = src
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
            p = (base / rest).resolve() if rest else base.resolve()
        elif src.startswith("./"):
            p = (launch_dir / src[2:]).resolve()
        elif src.startswith("/"):
            p = Path(src).resolve()
        else:
            p = (launch_dir / src).resolve()

        if not p.exists():
            self.err(f"not found: {src}")
            return 1

        filename     = p.name
        content_type = mimetypes.guess_type(str(p))[0] or "application/octet-stream"
        size         = p.stat().st_size

        # Resolve destination folder_id
        folder_id = self._resolve_dest_folder(client, dest)

        # Progress bar upload
        uploaded = [0]
        bar_w    = 30

        def draw(done: int) -> None:
            pct    = done / size if size else 1
            filled = int(bar_w * pct)
            bar    = "█" * filled + "░" * (bar_w - filled)
            from cli.base.color import Color
            sys.stderr.write(f"\r  {Color.dim(filename)}  [{Color.wrap(bar, Color.CYAN)}]  {done}/{size} B")
            sys.stderr.flush()

        class _Reader:
            def __init__(self, fobj):
                self._f = fobj
            def read(self, n=-1):
                chunk = self._f.read(n)
                if chunk:
                    uploaded[0] += len(chunk)
                    draw(uploaded[0])
                return chunk
            def __len__(self):
                return size

        draw(0)
        with open(p, "rb") as fobj:
            result = files_api.upload(
                client, _Reader(fobj), filename, content_type,
                folder_id=folder_id,
            )
        sys.stderr.write("\r\033[K")
        sys.stderr.flush()

        cache.add({
            "key":      result["key"],
            "filename": filename,
            "size":     _fmt_size(size),
            "exp":      result.get("expires_at", ""),
            "owner":    "",
        })
        self.success(f"uploaded {filename}")
        return 0

    # ---------------------------------------------------------------- download (drp → real)

    def _download(self, client, src: str, dest: str) -> int:
        key = self._filename_to_key(client, src)
        if key is None:
            self.err(f"not found in drp: {src}")
            return 1

        with self.spin("Fetching metadata"):
            meta = files_api.fetch(client, key)

        dest_path = Path(dest)
        if dest_path.is_dir() or dest.endswith("/"):
            dest_path = dest_path / meta.get("filename", src)

        import requests as _req
        url  = meta["download_url"]
        size = meta.get("size", 0)
        bar_w = 30

        resp = _req.get(url, stream=True, timeout=60)
        resp.raise_for_status()

        downloaded = 0
        with open(dest_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if size:
                        pct    = downloaded / size
                        filled = int(bar_w * pct)
                        bar    = "█" * filled + "░" * (bar_w - filled)
                        from cli.base.color import Color
                        sys.stderr.write(f"\r  {Color.dim(dest_path.name)}  [{Color.wrap(bar, Color.CYAN)}]  {downloaded}/{size} B")
                        sys.stderr.flush()

        sys.stderr.write("\r\033[K")
        sys.stderr.flush()
        self.success(f"saved {dest_path}")
        return 0

    # ---------------------------------------------------------------- drp → drp copy

    def _drp_copy(self, client, src: str, dest: str) -> int:
        key = self._filename_to_key(client, src)
        if key is None:
            self.err(f"not found in drp: {src}")
            return 1

        dest_folder_id = self._resolve_dest_folder(client, dest)
        dest_name      = src if _is_drp_dir(dest) else dest.rstrip("/")

        with self.spin("Copying"):
            # Download then re-upload — new key, 24h default
            meta = files_api.fetch(client, key)
            raw  = files_api.fetch_content(client, key)

        import io
        content_type = meta.get("content_type", "application/octet-stream")
        filename     = dest_name

        result = files_api.upload(
            client, io.BytesIO(raw), filename, content_type,
            folder_id=dest_folder_id,
        )
        cache.add({
            "key":      result["key"],
            "filename": filename,
            "size":     _fmt_size(len(raw)),
            "exp":      result.get("expires_at", ""),
            "owner":    "",
        })
        self.success(f"copied {src} → {dest_name}")
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

    def _resolve_dest_folder(self, client, dest: str) -> int | None:
        """Return folder_id for the destination, or current folder if dest is '.'"""
        if dest in (".", "./"):
            return self.config.get("shell", {}).get("cwd_id")
        # @username/ or @username — treat as the user's root (no folder)
        if dest.startswith("@"):
            return None
        if _is_drp_dir(dest) and not _is_real(dest):
            slug = dest.strip("/")
            try:
                folder_id = self.config.get("shell", {}).get("cwd_id")
                data = folders_api.list_contents(client, folder_id) if folder_id \
                       else folders_api.list_root(client)
                match = next((f for f in data.get("folders", []) if f["slug"] == slug), None)
                return match["id"] if match else None
            except Exception:
                pass
        return self.config.get("shell", {}).get("cwd_id")