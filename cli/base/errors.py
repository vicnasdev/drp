"""
cli/base/errors.py

DrpError hierarchy — known, user-facing failures. These are caught by
BaseCommand.execute() and printed cleanly without a crash report.

Also contains parse_response() — maps HTTP status codes to typed errors.
"""
from __future__ import annotations


class DrpError(Exception):
    """Expected failure. Printed cleanly, no bug report sent."""
    def __init__(self, message: str, code: int = 1):
        super().__init__(message)
        self.exit_code = code


class AuthError(DrpError):
    def __init__(self, message: str = "authentication required — run: drp login"):
        super().__init__(message)


class NotFoundError(DrpError):
    def __init__(self, ref: str = ""):
        super().__init__(f"not found: {ref}" if ref else "not found")


class PermissionDeniedError(DrpError):
    def __init__(self, ref: str = ""):
        msg = f"you don't own {ref}" if ref else "permission denied"
        super().__init__(msg + " — use --fork to make your own copy")


class PlanError(DrpError):
    def __init__(self, feature: str):
        super().__init__(
            f"{feature} is not available on your plan — upgrade at drp.fyi/billing/"
        )


class NetworkError(DrpError):
    def __init__(self, message: str = "could not reach the server — check your connection"):
        super().__init__(message)


class KeyTakenError(DrpError):
    def __init__(self, key: str):
        super().__init__(f"key '{key}' is already taken — choose a different one")


class FileTooLargeError(DrpError):
    def __init__(self) -> None:
        super().__init__("file too large for your plan — upgrade at drp.fyi/billing/")


def parse_response(resp: "requests.Response") -> dict:  # noqa: F821
    """
    Parse a JSON API response. Maps HTTP errors to typed DrpError subclasses.
    Never surfaces raw server internals to the user.
    """
    try:
        data = resp.json()
    except Exception:
        raise NetworkError("server returned an unexpected response")

    match resp.status_code:
        case 200 | 201:
            return data
        case 401:
            raise AuthError(data.get("error", "authentication required"))
        case 403:
            server_msg = data.get("error", "")
            # If the server gave us a specific reason (e.g. "email not verified"),
            # surface it directly instead of the generic "permission denied" message.
            if server_msg and server_msg != "permission denied":
                raise DrpError(server_msg)
            raise PermissionDeniedError(data.get("key", ""))
        case 404:
            raise NotFoundError(data.get("key", ""))
        case 409:
            # A 409 from a folder delete means "not empty"; from a file upload
            # it means "key already taken". Distinguish by checking the error body.
            err_msg = data.get("error", "")
            if "not empty" in err_msg:
                raise DrpError(err_msg + " — pass --recursive to delete recursively")
            raise KeyTakenError(data.get("key", ""))
        case 413:
            raise FileTooLargeError()
        case 429:
            raise DrpError("rate limited — wait a moment and try again")
        case _:
            if not resp.ok:
                raise DrpError(data.get("error", f"server error ({resp.status_code})"))
            return data
