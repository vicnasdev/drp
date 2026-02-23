"""
core/views/tokens.py

API token CRUD endpoints (paid accounts only).

POST /auth/tokens/create/   — create a new API token
GET  /auth/tokens/           — list tokens for the current user
POST /auth/tokens/<id>/revoke/ — revoke (delete) a token
"""

import hashlib
import json
import secrets

from django.http import JsonResponse
from django.utils import timezone
from datetime import timedelta

from core.models import APIToken, Plan


def _require_auth_json(request):
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Login required."}, status=401)
    return None


def _require_paid(request):
    err = _require_auth_json(request)
    if err:
        return err
    if not hasattr(request.user, "profile") or not request.user.profile.is_paid:
        return JsonResponse({"error": "API keys are a paid feature."}, status=403)
    return None


def _parse_expires(value: str | None):
    """Parse '90d', '24h', etc. into a datetime, or None."""
    if not value:
        return None
    value = value.strip().lower()
    try:
        if value.endswith("d"):
            return timezone.now() + timedelta(days=int(value[:-1]))
        if value.endswith("h"):
            return timezone.now() + timedelta(hours=int(value[:-1]))
        # bare int → days
        return timezone.now() + timedelta(days=int(value))
    except (ValueError, OverflowError):
        return None


def create_token(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST required."}, status=405)

    err = _require_paid(request)
    if err:
        return err

    # Quota check
    api_keys_limit = Plan.get(request.user.profile.plan, "api_keys")
    if api_keys_limit is not None:
        current = APIToken.objects.filter(user=request.user).count()
        if current >= api_keys_limit:
            return JsonResponse(
                {"error": f"API key limit reached ({api_keys_limit})."},
                status=403,
            )

    try:
        data = json.loads(request.body) if request.body else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        data = {}

    label = (data.get("label") or "").strip()[:120]
    expires = _parse_expires(data.get("expires"))

    raw_token = secrets.token_urlsafe(48)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    prefix = raw_token[:8]

    APIToken.objects.create(
        user=request.user,
        token_hash=token_hash,
        prefix=prefix,
        label=label,
        expires_at=expires,
    )

    return JsonResponse({
        "token": raw_token,  # only time it's shown
        "prefix": prefix,
        "label": label,
        "expires_at": expires.isoformat() if expires else None,
    }, status=201)


def list_tokens(request):
    if request.method != "GET":
        return JsonResponse({"error": "GET required."}, status=405)

    err = _require_auth_json(request)
    if err:
        return err

    tokens = APIToken.objects.filter(user=request.user).order_by("-created_at")
    return JsonResponse({
        "tokens": [
            {
                "id": t.pk,
                "prefix": t.prefix,
                "label": t.label,
                "created_at": t.created_at.isoformat(),
                "expires_at": t.expires_at.isoformat() if t.expires_at else None,
                "last_used": t.last_used.isoformat() if t.last_used else None,
                "expired": t.is_expired(),
            }
            for t in tokens
        ],
    })


def revoke_token(request, token_id):
    if request.method != "POST":
        return JsonResponse({"error": "POST required."}, status=405)

    err = _require_auth_json(request)
    if err:
        return err

    deleted, _ = APIToken.objects.filter(pk=token_id, user=request.user).delete()
    if not deleted:
        return JsonResponse({"error": "Token not found."}, status=404)

    return JsonResponse({"message": "Token revoked."})
