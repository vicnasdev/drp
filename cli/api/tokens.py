"""
cli/api/tokens.py

API calls for account-level API token management.
"""
from __future__ import annotations

from .client import APIClient
from cli.base.errors import parse_response


def create(client: APIClient, label: str = "") -> dict:
    """Returns {"token": "<raw>", "id": ..., "label": ...} — raw token shown once."""
    return parse_response(client.post("/api/v1/tokens/", json={"label": label}))


def list_all(client: APIClient) -> list[dict]:
    return parse_response(client.get("/api/v1/tokens/")).get("results", [])


def revoke(client: APIClient, token_id: int) -> None:
    parse_response(client.delete(f"/api/v1/tokens/{token_id}/"))
