"""
core/api/auth.py

Bearer token authentication for CLI API views.
Uses the existing APIToken model (SHA-256 hashed storage).
"""
from __future__ import annotations

import hashlib
import secrets
import functools

from django.http import JsonResponse
from .models import APIToken


def _get_raw_token(request) -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    return None


def token_required(view_func):
    """Decorator: require a valid Bearer token. Sets request.auth_token."""
    @functools.wraps(view_func)
    def wrapper(request, *args, **kwargs):
        raw = _get_raw_token(request)
        if not raw:
            return JsonResponse({"error": "authentication required"}, status=401)
        token_hash = hashlib.sha256(raw.encode()).hexdigest()
        try:
            token_obj = APIToken.objects.select_related("user").get(token_hash=token_hash)
        except APIToken.DoesNotExist:
            return JsonResponse({"error": "invalid token"}, status=401)
        request.user       = token_obj.user
        request.auth_token = token_obj
        return view_func(request, *args, **kwargs)
    return wrapper


def issue_token(user, label: str = "cli") -> tuple[APIToken, str]:
    """
    Create a new APIToken for user.
    Returns (token_obj, raw_token) — raw_token is shown once and never stored.
    """
    raw        = secrets.token_hex(32)
    token_hash = hashlib.sha256(raw.encode()).hexdigest()
    token_obj  = APIToken.objects.create(user=user, token_hash=token_hash, label=label)
    return token_obj, raw


def revoke_token(token_obj: APIToken) -> None:
    token_obj.delete()