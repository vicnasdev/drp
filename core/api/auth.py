"""
core/api/auth.py

Bearer token authentication for CLI API views.
Uses Knox / DRF token — swap issue_token/revoke_token for your token model.
"""
from __future__ import annotations

import functools
from django.http import JsonResponse

# ── Swap these imports for whatever token model you use ──────────────────────
# Option A — Django REST Framework
# from rest_framework.authtoken.models import Token
#
# Option B — Knox
# from knox.models import AuthToken
#
# Option C — roll your own (example below uses a simple APIToken model)
# from core.models import APIToken
# ----------------------------------------------------------------------------


def _get_token_from_request(request):
    """Extract raw token string from Authorization: Bearer <token> header."""
    header = request.META.get("HTTP_AUTHORIZATION", "")
    if header.startswith("Bearer "):
        return header[7:]
    return None


def token_required(view_func):
    """Decorator: require a valid Bearer token. Sets request.user and request.auth_token."""
    @functools.wraps(view_func)
    def wrapper(request, *args, **kwargs):
        raw = _get_token_from_request(request)
        if not raw:
            return JsonResponse({"error": "authentication required"}, status=401)

        # ── Replace this block with your token lookup ────────────────────────
        # Example with DRF Token:
        # from rest_framework.authtoken.models import Token
        # try:
        #     token = Token.objects.select_related("user").get(key=raw)
        # except Token.DoesNotExist:
        #     return JsonResponse({"error": "invalid token"}, status=401)
        # request.user       = token.user
        # request.auth_token = token
        # --------------------------------------------------------------------

        # TODO: implement token lookup
        return JsonResponse({"error": "token auth not implemented"}, status=501)

        return view_func(request, *args, **kwargs)  # noqa: unreachable — remove TODO above
    return wrapper


def issue_token(user) -> object:
    """Create and return a new auth token for user."""
    # Example with DRF Token:
    # from rest_framework.authtoken.models import Token
    # token, _ = Token.objects.get_or_create(user=user)
    # return token
    raise NotImplementedError("implement issue_token for your token model")


def revoke_token(token) -> None:
    """Delete / invalidate the given token."""
    # token.delete()
    raise NotImplementedError("implement revoke_token for your token model")