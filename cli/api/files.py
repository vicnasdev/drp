"""
cli/api/files.py

API calls scoped to file/drop operations.
"""
from __future__ import annotations

from pathlib import Path
from typing import BinaryIO

from .client import APIClient
from cli.base.errors import parse_response


def upload(
    client: APIClient,
    file_obj: BinaryIO,
    filename: str,
    content_type: str,
    *,
    key: str | None       = None,
    burn: bool            = False,
    password: str | None  = None,
    encrypted: bool       = False,
    expires: str | None   = None,
    public: bool          = False,
    tags: list[str]       | None = None,
    schedule: str | None  = None,
    webhook: str | None   = None,
    folder_id: int | None = None,
) -> dict:
    extra = {
        k: v for k, v in {
            "key":       key,
            "burn":      "true" if burn else None,
            "password":  password,
            "encrypted": "true" if encrypted else None,
            "expires":   expires,
            "public":    "true" if public else None,
            "tags":      ",".join(tags) if tags else None,
            "schedule":  schedule,
            "webhook":   webhook,
            "folder_id": folder_id,
        }.items() if v is not None
    }
    resp = client.upload("/api/v1/files/", file_obj, filename, content_type, extra)
    return parse_response(resp)


def fetch(client: APIClient, key: str) -> dict:
    """Fetch drop metadata + signed download URL."""
    return parse_response(client.get(f"/api/v1/files/{key}/"))


def fetch_content(client: APIClient, key: str) -> bytes:
    """Download raw file bytes via B2 signed URL."""
    import requests as _req
    meta    = fetch(client, key)
    url     = meta["download_url"]
    resp    = _req.get(url, timeout=60)
    resp.raise_for_status()
    return resp.content


def delete(client: APIClient, key: str) -> None:
    parse_response(client.delete(f"/api/v1/files/{key}/"))


def fork(client: APIClient, key: str, new_key: str | None = None) -> dict:
    """Create an independent owned copy of any drop."""
    payload = {}
    if new_key:
        payload["key"] = new_key
    return parse_response(client.post(f"/api/v1/files/{key}/fork/", json=payload))


def setkey(client: APIClient, old_key: str, new_key: str) -> dict:
    return parse_response(client.patch(f"/api/v1/files/{old_key}/", json={"key": new_key}))


def update_meta(client: APIClient, key: str, **fields) -> dict:
    """Patch arbitrary metadata fields (public, tags, expires, password, locked)."""
    return parse_response(client.patch(f"/api/v1/files/{key}/", json=fields))
