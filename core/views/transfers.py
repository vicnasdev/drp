"""
core/views/transfers.py

Drop ownership transfer via one-time tokens.

POST /<key>/send/    — generate a transfer token (owner only)
POST /claim/<token>/ — claim ownership with a transfer token (logged-in user)
"""

import secrets

from django.http import JsonResponse
from django.utils import timezone
from datetime import timedelta

from core.models import Drop, TransferToken


TRANSFER_TTL_HOURS = 24


def send_transfer(request, key, ns="c"):
    """Generate a one-time transfer token for a drop. Owner only."""
    if request.method != "POST":
        return JsonResponse({"error": "POST required."}, status=405)
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Login required."}, status=401)

    drop = Drop.objects.filter(ns=ns, key=key, owner=request.user).first()
    if not drop:
        return JsonResponse({"error": "Drop not found or not yours."}, status=404)

    # Revoke any existing pending tokens for this drop
    TransferToken.objects.filter(
        drop=drop, claimed_by__isnull=True,
    ).update(expires_at=timezone.now())

    token = secrets.token_urlsafe(32)
    TransferToken.objects.create(
        drop=drop,
        token=token,
        created_by=request.user,
        expires_at=timezone.now() + timedelta(hours=TRANSFER_TTL_HOURS),
    )

    return JsonResponse({
        "token": token,
        "expires_in": f"{TRANSFER_TTL_HOURS}h",
        "key": drop.key,
        "ns": drop.ns,
    })


def claim_transfer(request, token):
    """Claim a drop via transfer token. Logged-in user becomes the new owner."""
    if request.method != "POST":
        return JsonResponse({"error": "POST required."}, status=405)
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Login required."}, status=401)

    tt = TransferToken.objects.select_related("drop", "created_by").filter(
        token=token,
    ).first()

    if not tt:
        return JsonResponse({"error": "Invalid transfer token."}, status=404)
    if not tt.is_valid():
        return JsonResponse({"error": "Transfer token expired or already used."}, status=410)
    if tt.created_by == request.user:
        return JsonResponse({"error": "Cannot transfer to yourself."}, status=400)

    drop = tt.drop
    old_owner = drop.owner

    # Transfer ownership
    drop.owner = request.user
    drop.anon_token = None  # clear anon ownership
    drop.save(update_fields=["owner", "anon_token"])

    # Mark token as claimed
    tt.claimed_by = request.user
    tt.claimed_at = timezone.now()
    tt.save(update_fields=["claimed_by", "claimed_at"])

    prefix = "f/" if drop.ns == Drop.NS_FILE else ""
    return JsonResponse({
        "key": drop.key,
        "ns": drop.ns,
        "url": f"/{prefix}{drop.key}/",
        "from": old_owner.username if old_owner else None,
    })
