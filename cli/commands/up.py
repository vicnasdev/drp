"""
cli/commands/both/up.py

Upload a file, stdin, URL, directory, or glob.

  drp up notes.md
  drp up notes.md -k my-notes --expires 7d
  drp up src/ -k myproject          # creates folder, prompts if exists
  drp up "*.py" -k snippets
  drp up - < notes.md               # stdin
"""
from __future__ import annotations

import argparse
import mimetypes
import os
import sys
from pathlib import Path

from cli.base import SpinnerCommand, AuthCommand
from cli.api import APIClient, files as files_api, folders as folders_api
from cli import cache


class UpCommand(SpinnerCommand, AuthCommand):
    name        = "up"
    description = "Upload a file, directory, or glob"

    def run(self, args: list[str]) -> int:
        self.require_auth()
        opts = _parse(args)

        client = APIClient.from_config(self.config, authed=True)

        # stdin
        if opts.target == "-":
            return self._upload_single(client, sys.stdin.buffer, "<stdin>", opts)

        # explicit text upload
        if opts.text:
            import io
            return self._upload_single(client, io.BytesIO(opts.target.encode()), "<text>", opts)

        # glob
        if "*" in opts.target:
            targets = list(Path(".").glob(opts.target))
            if not targets:
                self.bail(f"no files matched: {opts.target}")
            return self._upload_folder(client, targets, opts)

        # FIX: resolve path relative to real process CWD so that paths typed
        # inside the shell (which has a *virtual* CWD, not a real fs one) still
        # resolve correctly. Path.resolve() already does this — the bug was that
        # '../file.txt' would resolve to a path that doesn't exist from the
        # shell's virtual perspective. We now also check the path relative to
        # the actual working directory the process was launched from, which is
        # always correct regardless of virtual shell CWD.
        p = Path(opts.target).expanduser()
        if not p.is_absolute():
            p = Path(os.getcwd()) / p
        p = p.resolve()

        if not p.exists():
            self.bail(f"'{opts.target}' not found — use --text to upload a string")
        if p.is_file():
            return self._upload_single(client, None, str(p), opts)

        # directory → folder upload
        return self._upload_folder(client, [p], opts)

    # ---------------------------------------------------------------- single

    def _upload_single(self, client, file_obj, path_str: str, opts) -> int:
        p            = Path(path_str) if path_str not in ("<stdin>", "<text>") else None
        filename     = p.name if p else ("stdin" if path_str == "<stdin>" else "text")
        content_type = _mime(p) if p else "text/plain"

        if opts.encrypt:
            from cli.base.crypto import encrypt
            file_obj, content_type = encrypt(file_obj or open(p, "rb"), opts.encrypt)  # noqa
        else:
            file_obj = file_obj or open(p, "rb")  # noqa

        # Auto-rename if a drop with the same filename already exists in the cache.
        # FIX: without this, uploading file1.txt twice produced two identical-looking
        # rows in `ls` with different keys — confusing and impossible to disambiguate
        # visually. We rename client-side (file1 (1).txt, file1 (2).txt ...) before
        # upload so the stored filename is unique.
        filename = _unique_filename(filename)

        # FIX: replace the opaque spinner with a real progress bar for file uploads.
        # For stdin/text (unknown size) we keep the spinner since we can't show %.
        size = _file_size(file_obj, p)
        if size is not None and size > 0:
            result = _upload_with_progress(
                self, client, file_obj, filename, content_type, size, opts
            )
        else:
            with self.spin(f"Uploading {filename}"):
                result = files_api.upload(
                    client, file_obj, filename, content_type,
                    key=opts.key, burn=opts.burn, password=opts.password,
                    encrypted=bool(opts.encrypt), expires=opts.expires,
                    public=opts.public, tags=opts.tag or [],
                    schedule=opts.schedule, webhook=opts.webhook,
                )

        cache.add({
            "key":      result["key"],
            "filename": filename,
            "size":     _fmt_size(result.get("size", 0)),
            "exp":      result.get("expires_at", ""),
            "owner":    "",
        })
        self.print_key(result["key"], self.server_url)
        return 0

    # ---------------------------------------------------------------- folder

    def _upload_folder(self, client, targets: list[Path], opts) -> int:
        slug = opts.key or Path(targets[0].parent if targets[0].is_file() else targets[0]).name

        folder_id = _ensure_folder(client, slug, self.confirm)
        if folder_id is None:
            self.abort("cancelled")

        files = []
        for t in targets:
            if t.is_dir():
                files += [f for f in t.rglob("*") if f.is_file() and not _ignored(f)]
            elif t.is_file():
                files.append(t)

        self.info(f"Uploading {len(files)} file(s) → {slug}/")
        for f in files:
            with self.spin(f.name):
                with open(f, "rb") as fobj:
                    files_api.upload(
                        client, fobj, f.name, _mime(f),
                        public=opts.public, tags=opts.tag or [],
                        folder_id=folder_id,
                    )
        self.success(f"{len(files)} files uploaded to /@{self.username}/{slug}/")
        return 0


# ------------------------------------------------------------------ progress

def _unique_filename(filename: str) -> str:
    """
    If a drop with this filename already exists in the local cache, append
    (1), (2) ... until the name is unique — same behaviour as macOS/Windows
    file copy. This prevents duplicate-looking rows in `ls`.
    """
    from cli import cache as cache_store
    existing = {e.get("filename", "") for e in cache_store.all_entries()}
    if filename not in existing:
        return filename
    stem, _, ext = filename.rpartition(".")
    if not stem:          # no extension
        stem, ext = filename, ""
    else:
        ext = "." + ext
    i = 1
    while True:
        candidate = f"{stem} ({i}){ext}"
        if candidate not in existing:
            return candidate
        i += 1


def _file_size(file_obj, path: Path | None) -> int | None:
    """Return file size in bytes if knowable, else None."""
    if path and path.exists():
        return path.stat().st_size
    try:
        pos = file_obj.tell()
        file_obj.seek(0, 2)
        size = file_obj.tell()
        file_obj.seek(pos)
        return size
    except Exception:
        return None


def _upload_with_progress(cmd, client, file_obj, filename, content_type, size, opts) -> dict:
    """Stream upload with a live terminal progress bar."""
    import sys
    from cli.base.color import Color

    uploaded  = [0]
    bar_width = 30

    def _draw(done: int) -> None:
        pct   = done / size
        filled = int(bar_width * pct)
        bar   = "█" * filled + "░" * (bar_width - filled)
        label = f"{_fmt_size(done)}/{_fmt_size(size)}"
        sys.stderr.write(f"\r  {Color.dim(filename)}  [{Color.wrap(bar, Color.CYAN)}]  {Color.dim(label)}")
        sys.stderr.flush()

    class _ProgressReader:
        """Wraps a file-like object and draws progress on each read."""
        def __init__(self, fobj):
            self._f = fobj

        def read(self, n=-1):
            chunk = self._f.read(n)
            if chunk:
                uploaded[0] += len(chunk)
                _draw(uploaded[0])
            return chunk

        # requests needs these for multipart
        def __len__(self):
            return size

    _draw(0)
    result = files_api.upload(
        client, _ProgressReader(file_obj), filename, content_type,
        key=opts.key, burn=opts.burn, password=opts.password,
        encrypted=bool(opts.encrypt), expires=opts.expires,
        public=opts.public, tags=opts.tag or [],
        schedule=opts.schedule, webhook=opts.webhook,
    )
    sys.stderr.write("\r\033[K")  # clear progress line
    sys.stderr.flush()
    return result


# ------------------------------------------------------------------ helpers

def _ensure_folder(client, slug: str, confirm_fn) -> int | None:
    try:
        result = folders_api.create(client, slug)
        return result["id"]
    except Exception:
        if confirm_fn(f"folder '{slug}' already exists. append?", default=False):
            result = folders_api.list_root(client)
            match  = next((f for f in result.get("folders", []) if f["slug"] == slug), None)
            return match["id"] if match else None
        return None


def _mime(p: Path | None) -> str:
    if p is None:
        return "text/plain"
    mime, _ = mimetypes.guess_type(str(p))
    return mime or "application/octet-stream"


def _fmt_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _ignored(p: Path) -> bool:
    ignored_dirs  = {".git", "__pycache__", ".DS_Store"}
    ignored_exts  = {".pyc", ".pyo"}
    return any(part in ignored_dirs for part in p.parts) or p.suffix in ignored_exts


def _parse(args):
    p = argparse.ArgumentParser(prog="up", add_help=False)
    p.add_argument("target")
    p.add_argument("-k", "--key",      default=None)
    p.add_argument("--burn",           action="store_true")
    p.add_argument("--password",       default=None)
    p.add_argument("--encrypt",        default=None, metavar="PASSPHRASE")
    p.add_argument("--expires",        default=None)
    p.add_argument("--public",         action="store_true")
    p.add_argument("--tag",            action="append")
    p.add_argument("--schedule",       default=None)
    p.add_argument("--webhook",        default=None)
    p.add_argument("--text",           action="store_true", help="treat target as literal text content")
    return p.parse_args(args)
