"""
cli/api/client.py

Thin requests wrapper. All HTTP in the codebase goes through here.
Handles: base URL, auth header injection, timeout, connection errors.
Swap requests for httpx here without touching any command.
"""
from __future__ import annotations

import requests
from requests import Response

from cli.base.errors import NetworkError


DEFAULT_TIMEOUT = 30


class APIClient:

    def __init__(self, base_url: str, token: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.token    = token

    # ---------------------------------------------------------------- HTTP

    def get(self, path: str, **kwargs) -> Response:
        return self._request("GET", path, **kwargs)

    def post(self, path: str, **kwargs) -> Response:
        return self._request("POST", path, **kwargs)

    def patch(self, path: str, **kwargs) -> Response:
        return self._request("PATCH", path, **kwargs)

    def delete(self, path: str, **kwargs) -> Response:
        return self._request("DELETE", path, **kwargs)

    def upload(self, path: str, file_obj, filename: str, content_type: str, extra: dict | None = None) -> Response:
        """Multipart file upload."""
        files = {"file": (filename, file_obj, content_type)}
        data  = extra or {}
        return self._request("POST", path, files=files, data=data)

    # ---------------------------------------------------------------- internal

    def _request(self, method: str, path: str, **kwargs) -> Response:
        url     = f"{self.base_url}/{path.lstrip('/')}"
        headers = kwargs.pop("headers", {})
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        kwargs.setdefault("timeout", DEFAULT_TIMEOUT)
        try:
            return requests.request(method, url, headers=headers, **kwargs)
        except requests.ConnectionError:
            raise NetworkError("could not reach the server — check your connection")
        except requests.Timeout:
            raise NetworkError("request timed out")
        except requests.RequestException as e:
            raise NetworkError(str(e))

    # ---------------------------------------------------------------- factory

    @classmethod
    def from_config(cls, config: dict, authed: bool = False) -> "APIClient":
        url   = config.get("server", {}).get("url", "https://drp.fyi")
        token = config.get("auth", {}).get("token", "") if authed else None
        return cls(url, token or None)
