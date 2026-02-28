"""
cli/api/folders.py

API calls scoped to folder operations.
"""
from __future__ import annotations

from .client import APIClient
from cli.base.errors import parse_response


def create(client: APIClient, slug: str, parent_id: int | None = None, public: bool = False) -> dict:
    return parse_response(client.post("/api/v1/folders/", json={
        "slug":      slug,
        "parent_id": parent_id,
        "public":    public,
    }))


def list_contents(client: APIClient, folder_id: int) -> dict:
    """Returns folder metadata + items list."""
    return parse_response(client.get(f"/api/v1/folders/{folder_id}/"))


def list_root(client: APIClient) -> dict:
    """
    Returns top-level folders + loose drops for the authenticated user.
    FIX: previously only returned folder objects from GET /api/v1/folders/.
    Now also fetches loose drops from GET /api/v1/files/ and merges them,
    so shell `ls` at root shows everything the user owns.
    """
    folders_data = parse_response(client.get("/api/v1/folders/"))
    try:
        files_data = parse_response(client.get("/api/v1/files/"))
        folders_data["items"] = files_data.get("items", [])
    except Exception:
        # If the files endpoint fails for any reason, still return folders
        folders_data.setdefault("items", [])
    return folders_data


def move(client: APIClient, folder_id: int, new_parent_id: int | None) -> dict:
    return parse_response(client.patch(f"/api/v1/folders/{folder_id}/", json={
        "parent_id": new_parent_id,
    }))


def rename(client: APIClient, folder_id: int, slug: str) -> dict:
    return parse_response(client.patch(f"/api/v1/folders/{folder_id}/", json={"slug": slug}))


def delete(client: APIClient, folder_id: int, recursive: bool = False) -> None:
    parse_response(client.delete(f"/api/v1/folders/{folder_id}/", params={"recursive": recursive}))


def resolve_path(client: APIClient, path: str) -> dict:
    """
    Resolve a shell path like /@vic/docs/sub to a folder or file object.
    Returns {"type": "folder"|"file", "object": {...}}
    """
    return parse_response(client.get("/api/v1/resolve/", params={"path": path}))