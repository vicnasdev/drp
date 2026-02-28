"""
core/api/auth.py

API token authentication helpers.

Provides:
  - issue_token(user, label="")  → (APIToken, raw_token_str)
  - revoke_token(token_obj)
  - token_required               decorator — attaches request.user and
                                 request.auth_token or returns 401
"""
from __future__ import annotations

import hashlib
import secrets
from functools import wraps

from django.contrib.auth import get_user_model
from django.http import JsonResponse
from django.utils import timezone

from core.models import APIToken

User = get_user_model()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def issue_token(user, label: str = "") -> tuple[APIToken, str]:
    """
    Create and persist a new API token for *user*.

    Returns (APIToken instance, raw token string).
    The raw string is shown once and never stored in plain text.
    """
    raw        = secrets.token_urlsafe(32)
    token_obj  = APIToken.objects.create(
        user       = user,
        token_hash = _hash(raw),
        label      = label or "",
    )
    return token_obj, raw


def revoke_token(token_obj: APIToken) -> None:
    """Delete the given APIToken from the database."""
    token_obj.delete()


def token_required(view_func):
    """
    Decorator that enforces Bearer-token authentication.

    Reads:   Authorization: Bearer <raw_token>
    On success: sets request.user and request.auth_token, then calls the view.
    On failure: returns 401 JSON.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JsonResponse({"error": "authentication required"}, status=401)

        raw = auth_header[len("Bearer "):]
        try:
            token_obj = APIToken.objects.select_related("user").get(
                token_hash=_hash(raw)
            )
        except APIToken.DoesNotExist:
            return JsonResponse({"error": "invalid token"}, status=401)

        # Stamp last_used (best-effort; don't blow up the request on failure)
        try:
            APIToken.objects.filter(pk=token_obj.pk).update(last_used=timezone.now())
        except Exception:
            pass

        request.user       = token_obj.user
        request.auth_token = token_obj
        return view_func(request, *args, **kwargs)

    return wrapper
