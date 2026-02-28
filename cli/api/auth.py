"""
cli/api/auth.py

API calls for authentication.
"""
from __future__ import annotations

from .client import APIClient
from cli.base.errors import parse_response


def login_password(client: APIClient, username: str, password: str) -> dict:
    """Returns {"token": "...", "username": "..."}"""
    return parse_response(client.post("/api/v1/auth/login/", json={
        "username": username,
        "password": password,
    }))


def login_token(client: APIClient, token: str) -> dict:
    """Validate a raw API token. Returns {"username": "..."}"""
    authed = APIClient(client.base_url, token)
    return parse_response(authed.get("/api/v1/auth/me/"))


def logout(client: APIClient) -> None:
    parse_response(client.post("/api/v1/auth/logout/"))


def whoami(client: APIClient) -> dict:
    return parse_response(client.get("/api/v1/auth/me/"))


def ping(client: APIClient) -> dict:
    return parse_response(client.get("/api/v1/ping/"))
