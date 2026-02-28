"""
cli/api/share.py

API calls for folder share token management.
"""
from __future__ import annotations

from .client import APIClient
from cli.base.errors import parse_response


def create(
    client: APIClient,
    folder_id: int,
    *,
    role: str            = "reader",
    expires: str | None  = None,
    group_id: int | None = None,
) -> dict:
    """Returns {"token": "...", "url": "...", "id": ...}"""
    return parse_response(client.post("/api/v1/share/", json={
        "folder_id": folder_id,
        "role":      role,
        "expires":   expires,
        "group_id":  group_id,
    }))


def list_for_folder(client: APIClient, folder_id: int) -> list[dict]:
    return parse_response(
        client.get("/api/v1/share/", params={"folder_id": folder_id})
    ).get("results", [])


def revoke(client: APIClient, token_id: int) -> None:
    parse_response(client.delete(f"/api/v1/share/{token_id}/"))
