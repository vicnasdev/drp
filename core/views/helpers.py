"""
Shared helpers: rate limiting, plan limits, B2 storage, key generation,
anon drop claiming.

Cloudinary has been removed.  All file storage goes through core/views/b2.py.
"""

import secrets

from django.core.cache import cache
from django.db import models as db_models

from core.models import Drop, Plan, UserProfile


# ── IP / rate limiting ────────────────────────────────────────────────────────

def client_ip(request):
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    return xff.split(",")[0].strip() if xff else request.META.get("REMOTE_ADDR", "")


def check_signup_rate(request):
    """Max 3 signups per IP per hour. Returns True if allowed."""
    key = f"signup_rate:{client_ip(request)}"
    count = cache.get(key, 0)
    if count >= 3:
        return False
    cache.set(key, count + 1, timeout=3600)
    return True


# ── Plan helpers ──────────────────────────────────────────────────────────────

def user_plan(user):
    if not user.is_authenticated:
        return Plan.ANON
    return getattr(getattr(user, "profile", None), "plan", Plan.FREE)


def max_file_bytes(user):
    return Plan.get(user_plan(user), "max_file_mb") * 1024 * 1024


def max_text_bytes(user):
    return Plan.get(user_plan(user), "max_text_kb") * 1024


def storage_ok(user, extra_bytes):
    if not user.is_authenticated:
        return True
    profile = getattr(user, "profile", None)
    if not profile:
        return True
    quota = profile.storage_quota_bytes
    if quota is None:
        return True
    return (profile.storage_used_bytes + extra_bytes) <= quota


def is_paid_user(user):
    return user.is_authenticated and user_plan(user) in (Plan.STARTER, Plan.PRO)


def max_lifetime_secs(user, ns):
    """
    Max total lifetime in seconds for activity-based expiry.
    Only applies to clipboard (ns='c') anon/free drops.
    """
    if ns != Drop.NS_CLIPBOARD:
        return None
    plan = user_plan(user)
    if plan == Plan.ANON:
        return 7 * 24 * 3600
    if plan == Plan.FREE:
        return 30 * 24 * 3600
    return None


# ── Username validation ───────────────────────────────────────────────────────

import re

_USERNAME_RE = re.compile(r'^[a-zA-Z0-9_-]{1,30}$')


def validate_username(username: str) -> str | None:
    """
    Validate a prospective username.
    Returns an error string if invalid, None if OK.
    """
    if not username:
        return 'Username is required.'
    if not _USERNAME_RE.match(username):
        return 'Username may only contain letters, numbers, hyphens and underscores (max 30 chars).'
    return None


# ── Key generation ────────────────────────────────────────────────────────────

def is_valid_drop_key(key: str) -> bool:
    """Drop keys must not start with @ (reserved for user namespaces)."""
    return bool(key) and not key.startswith('@')


def gen_key(ns):
    key = secrets.token_urlsafe(6)
    # token_urlsafe never produces @, but be explicit for safety
    while Drop.objects.filter(ns=ns, key=key).exists() or not is_valid_drop_key(key):
        key = secrets.token_urlsafe(6)
    return key


# ── B2 storage (thin wrappers kept here for import compatibility) ─────────────

def upload_to_b2(file_obj, ns: str, drop_key: str,
                 content_type: str = "application/octet-stream") -> str:
    """
    Upload a Django InMemoryUploadedFile / TemporaryUploadedFile to B2.
    Returns the B2 object key.  Raises on failure.
    """
    from core.views.b2 import upload_fileobj
    return upload_fileobj(file_obj, ns, drop_key, content_type)


def delete_from_b2(ns: str, drop_key: str) -> bool:
    """Delete a file from B2. Returns True on success or already-gone."""
    from core.views.b2 import delete_object
    return delete_object(ns, drop_key)


# ── Storage accounting ────────────────────────────────────────────────────────

def add_storage(user, bytes_delta):
    if user and user.is_authenticated and bytes_delta:
        UserProfile.objects.filter(user=user).update(
            storage_used_bytes=db_models.F("storage_used_bytes") + bytes_delta
        )


def sub_storage(owner_id, bytes_amount):
    if owner_id and bytes_amount:
        UserProfile.objects.filter(user_id=owner_id).update(
            storage_used_bytes=db_models.F("storage_used_bytes") - bytes_amount
        )


# ── Anon drop claiming ────────────────────────────────────────────────────────

def claim_anon_drops(user, token):
    """
    Reassign all unclaimed anon drops with the given token to user.
    Upgrades their lifetime to free-tier limits and locks them to the account.
    Returns the number of drops claimed.
    """
    if not token:
        return 0
    drops = Drop.objects.filter(anon_token=token, owner=None)
    count = drops.count()
    if not count:
        return 0
    drops.update(
        owner=user,
        locked=True,
        locked_until=None,
        anon_token=None,
        max_lifetime_secs=db_models.Case(
            db_models.When(ns=Drop.NS_CLIPBOARD, then=30 * 24 * 3600),
            default=None,
            output_field=db_models.IntegerField(),
        ),
    )
    return count