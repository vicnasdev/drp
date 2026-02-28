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

        targets = list(Path(".").glob(opts.target)) if "*" in opts.target else [Path(opts.target)]
        if not targets:
            self.bail(f"no files matched: {opts.target}")

        # single file
        if len(targets) == 1 and targets[0].is_file():
            return self._upload_single(client, None, str(targets[0]), opts)

        # not a real path
        if len(targets) == 1 and not targets[0].exists():
            if opts.text:
                import io
                return self._upload_single(client, io.BytesIO(opts.target.encode()), "<text>", opts)
            self.bail(f"'{opts.target}' not found — use --text to upload a string")

        # directory or glob → folder upload
        return self._upload_folder(client, targets, opts)

    # ---------------------------------------------------------------- single

    def _upload_single(self, client, file_obj, path_str: str, opts) -> int:
        p            = Path(path_str) if path_str != "<stdin>" else None
        filename     = p.name if p else "stdin"
        content_type = _mime(p) if p else "text/plain"

        if opts.encrypt:
            from cli.base.crypto import encrypt
            file_obj, content_type = encrypt(file_obj or open(p, "rb"), opts.encrypt)  # noqa
        else:
            file_obj = file_obj or open(p, "rb")  # noqa

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

        # check if folder exists
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