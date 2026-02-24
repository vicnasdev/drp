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


def check_password_attempt_rate(request, drop_key: str, ns: str = "c"):
    """
    Rate limit password attempts on protected drops.
    Max 10 attempts per IP per drop per hour.
    Returns (allowed: bool, remaining: int).
    """
    key = f"pw_attempt:{client_ip(request)}:{ns}:{drop_key}"
    count = cache.get(key, 0)
    max_attempts = 10
    if count >= max_attempts:
        return False, 0
    cache.set(key, count + 1, timeout=3600)
    return True, max_attempts - count - 1


def validate_webhook_url(url: str) -> str | None:
    """
    Validate webhook URL for security (SSRF prevention).
    - Must be http:// or https://
    - Cannot be internal/loopback IPs
    - Cannot use credentials in URL
    
    Returns error message if invalid, None if valid.
    """
    if not url:
        return None
    
    from urllib.parse import urlparse
    import ipaddress
    
    try:
        parsed = urlparse(url)
    except Exception:
        return "Invalid webhook URL format."
    
    # Check scheme
    if parsed.scheme not in ("http", "https"):
        return "Webhook URL must use http:// or https://."
    
    # Check for credentials in URL
    if parsed.username or parsed.password:
        return "Credentials in webhook URL are not allowed. Use headers instead."
    
    # Extract hostname (remove port)
    hostname = parsed.hostname or ""
    if not hostname:
        return "Webhook URL must have a valid hostname."
    
    # Check for localhost/loopback
    if hostname.lower() in ("localhost", "127.0.0.1", "[::1]", "::1"):
        return "Webhook URL cannot be localhost."
    
    # Check for private/reserved IP ranges
    try:
        ip = ipaddress.ip_address(hostname)
        if ip.is_private or ip.is_loopback or ip.is_reserved:
            return "Webhook URL cannot use private or reserved IP addresses."
    except ValueError:
        # Not an IP address, likely a domain name - ok
        pass
    
    return None


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


def can_user_access_collection(user, collection):
    """
    Check if user can access a collection they own.
    Returns (allowed: bool, reason: str | None).
    
    Based on plan quotas:
      - Free: 0 collections (cannot access any owned collections)
      - Starter: up to 10 collections
      - Pro: unlimited
      
    If user is downgraded and over quota, they cannot access excess collections.
    """
    if not user.is_authenticated or collection.owner_id != user.id:
        return False, "You don't own this collection."
    
    plan = user_plan(user)
    max_allowed = Plan.get(plan, "max_collections")
    
    if max_allowed == 0:
        return False, "Collections are a paid feature. Upgrade to Starter or Pro to access this collection."
    
    if max_allowed is None:
        # Pro: unlimited
        return True, None
    
    # Starter: check if user is within their quota
    # Count collections *in order of creation* so they keep access to oldest ones
    owned_count = collection.owner.collections.filter(parent=None).count()
    if owned_count <= max_allowed:
        return True, None
    
    # User is over quota — deny access to collections beyond the limit
    # Get the limit-th collection in creation order
    oldest_accessible = (
        collection.owner.collections
        .filter(parent=None)
        .order_by('created_at')[:max_allowed]
        .last()
    )
    
    if oldest_accessible and collection.created_at <= oldest_accessible.created_at:
        return True, None
    
    return (
        False,
        f"You've exceeded your collection limit ({max_allowed}). "
        "Upgrade to Pro for unlimited collections, or delete some collections to regain access."
    )


def can_user_access_group(user, group):
    """
    Check if user can access a group they created/own.
    Returns (allowed: bool, reason: str | None).
    
    Based on plan quotas:
      - Free: 0 groups (cannot access any owned groups)
      - Starter: up to 3 groups
      - Pro: unlimited
    """
    if not user.is_authenticated or group.created_by_id != user.id:
        return False, "You don't own this group."
    
    plan = user_plan(user)
    max_allowed = Plan.get(plan, "max_groups")
    
    if max_allowed == 0:
        return False, "Groups are a paid feature. Upgrade to Starter or Pro to access this group."
    
    if max_allowed is None:
        # Pro: unlimited
        return True, None
    
    # Starter: check if user is within their quota
    owned_count = group.created_by.created_groups.count()
    if owned_count <= max_allowed:
        return True, None
    
    # User is over quota — deny access to groups beyond the limit
    oldest_accessible = (
        group.created_by.created_groups
        .order_by('created_at')[:max_allowed]
        .last()
    )
    
    if oldest_accessible and group.created_at <= oldest_accessible.created_at:
        return True, None
    
    return (
        False,
        f"You've exceeded your group limit ({max_allowed}). "
        "Upgrade to Pro for unlimited groups, or delete some groups to regain access."
    )


def max_lifetime_secs(user, ns):
    """
    Max total lifetime in seconds for activity-based expiry.
    Only applies to clipboard (ns='c') anon/free drops.
    Reads clipboard_max_lifetime_days from the DB-driven PlanLimit.
    """
    if ns != Drop.NS_CLIPBOARD:
        return None
    plan = user_plan(user)
    days = Plan.get(plan, "clipboard_max_lifetime_days")
    return days * 24 * 3600 if days else None


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
    free_lifetime_secs = (Plan.get(Plan.FREE, "clipboard_max_lifetime_days") or 30) * 24 * 3600
    drops.update(
        owner=user,
        locked=True,
        locked_until=None,
        anon_token=None,
        max_lifetime_secs=db_models.Case(
            db_models.When(ns=Drop.NS_CLIPBOARD, then=free_lifetime_secs),
            default=None,
            output_field=db_models.IntegerField(),
        ),
    )
    return count


# ── QR code generation ───────────────────────────────────────────────────────

def qr_view(request):
    """GET /qr/?url=https://... — return a QR code as SVG."""
    from django.http import HttpResponse, HttpResponseBadRequest
    import io

    url = request.GET.get("url", "").strip()
    if not url:
        return HttpResponseBadRequest("Missing ?url= parameter")

    try:
        import qrcode
        import qrcode.image.svg

        factory = qrcode.image.svg.SvgPathImage
        qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10)
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(image_factory=factory)

        buf = io.BytesIO()
        img.save(buf)
        return HttpResponse(buf.getvalue(), content_type="image/svg+xml")
    except ImportError:
        return HttpResponseBadRequest("qrcode library not installed")