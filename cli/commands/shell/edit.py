"""
cli/commands/shell/edit.py

Edit a text file in $EDITOR. Re-uploads only if content changed.
Encrypted files: decrypt to tmp → edit → re-encrypt → upload.
Binary files: blocked.
"""
from __future__ import annotations
import argparse
import hashlib
import os
import subprocess
import tempfile
from pathlib import Path
from cli.base import SpinnerCommand, AuthCommand
from cli.base.errors import DrpError
from cli.api import APIClient, files as files_api


class EditCommand(SpinnerCommand, AuthCommand):
    name        = "edit"
    description = "Edit a text file in $EDITOR"

    def run(self, args: list[str]) -> int:
        self.require_auth()
        p = argparse.ArgumentParser(prog="edit", add_help=False)
        p.add_argument("ref")
        p.add_argument("--editor", default="")
        opts   = p.parse_args(args)
        client = APIClient.from_config(self.config, authed=True)

        editor = opts.editor or self.config.get("prefs", {}).get("editor") or os.environ.get("EDITOR", "")
        if not editor:
            self.bail("no editor set — use --editor vim or set $EDITOR")

        with self.spin("Fetching"):
            meta = files_api.fetch(client, opts.ref)
            raw  = files_api.fetch_content(client, opts.ref)

        if not _is_text(meta.get("content_type", "")):
            self.bail("edit only works on text files")

        passphrase = None
        if meta.get("is_encrypted"):
            from cli.base.crypto import decrypt, prompt_passphrase
            passphrase = prompt_passphrase()
            raw        = decrypt(raw, passphrase)

        original_hash = hashlib.sha256(raw).hexdigest()

        with tempfile.NamedTemporaryFile(suffix=_suffix(meta.get("filename", "")), delete=False) as tmp:
            tmp.write(raw)
            tmp_path = tmp.name

        try:
            subprocess.call([editor, tmp_path])
            new_content = Path(tmp_path).read_bytes()
        finally:
            os.unlink(tmp_path)

        if hashlib.sha256(new_content).hexdigest() == original_hash:
            self.dim("no changes — skipping upload")
            return 0

        import io
        content_type = meta.get("content_type", "text/plain")
        upload_obj   = io.BytesIO(new_content)

        if passphrase:
            from cli.base.crypto import encrypt
            upload_obj, content_type = encrypt(upload_obj, passphrase)

        with self.spin("Uploading changes"):
            files_api.upload(
                client, upload_obj, meta["filename"], content_type,
                key=meta["key"], encrypted=bool(passphrase),
            )

        self.success("updated")
        return 0


def _is_text(content_type: str) -> bool:
    return content_type.startswith("text/") or content_type in (
        "application/json", "application/xml", "application/javascript",
    )


def _suffix(filename: str) -> str:
    return Path(filename).suffix or ".txt"
