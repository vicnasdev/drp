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


def check_password_attempt_rate(request, drop_key: str):
    """
    Rate limit password attempts on protected drops.
    Max 10 attempts per IP per drop per hour.
    Returns (allowed: bool, remaining: int).
    """
    key = f"pw_attempt:{client_ip(request)}:{drop_key}"
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


def can_user_access_folder(user, folder):
    """
    Check if user can access a folder they own.
    Returns (allowed: bool, reason: str | None).
    
    Based on plan quotas:
      - Free: 0 folders (cannot access any owned folders)
      - Starter: up to 10 folders
      - Pro: unlimited
      
    If user is downgraded and over quota, they cannot access excess folders.
    Members (non-owners) always have access — quota only applies to the owner.
    """
    if not user.is_authenticated:
        return False, "You don't own this folder."
    
    # Members always have access — quota only constrains the owner
    if folder.owner_id != user.id:
        from core.models import FolderMember
        if folder.members.filter(user=user).exists():
            return True, None
        return False, "You don't have access to this folder."
    
    plan = user_plan(user)
    max_allowed = Plan.get(plan, "max_folders")
    
    if max_allowed == 0:
        return False, "Folders are a paid feature. Upgrade to Starter or Pro to access this folder."
    
    if max_allowed is None:
        # Pro: unlimited
        return True, None
    
    # Starter: check if user is within their quota
    owned_count = folder.owner.folders.filter(parent=None).count()
    if owned_count <= max_allowed:
        return True, None
    
    # User is over quota — deny access to folders beyond the limit
    accessible_ids = list(
        folder.owner.folders
        .filter(parent=None)
        .order_by('created_at')
        .values_list('pk', flat=True)[:max_allowed]
    )
    
    if folder.pk in accessible_ids:
        return True, None
    
    return (
        False,
        f"You've exceeded your folder limit ({max_allowed}). "
        "Upgrade to Pro for unlimited folders, or delete some folders to regain access."
    )


def max_lifetime_secs(user, is_text: bool = True):
    """
    Max total lifetime in seconds for activity-based expiry.
    Only applies to text drops.
    Reads clipboard_max_lifetime_days from the DB-driven PlanLimit.
    """
    if not is_text:
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

# Characters that are unsafe in URLs or get stripped by browsers
_UNSAFE_KEY_CHARS = set('#?%&+/\\:;@!=<>[]{}()|^~`"\' ')


def is_valid_drop_key(key: str) -> bool:
    """
    Drop keys must:
    - not be empty
    - not start with @ (reserved for user namespaces)
    - not contain URL-unsafe characters (#, ?, %, &, +, etc.)
    """
    if not key or key.startswith('@'):
        return False
    bad = _UNSAFE_KEY_CHARS.intersection(key)
    if bad:
        return False
    return True


def invalid_key_message(key: str) -> str | None:
    """Return an error message if the key is invalid, or None."""
    if not key:
        return 'Key cannot be empty.'
    if key.startswith('@'):
        return 'Keys cannot start with "@".'
    bad = _UNSAFE_KEY_CHARS.intersection(key)
    if bad:
        chars = ' '.join(sorted(bad))
        return f'Key contains forbidden characters: {chars}'
    return None


def gen_key():
    key = secrets.token_urlsafe(6)
    while Drop.objects.filter(key=key).exists() or not is_valid_drop_key(key):
        key = secrets.token_urlsafe(6)
    return key


# ── B2 storage (thin wrappers kept here for import compatibility) ─────────────

def upload_to_b2(file_obj, drop_key: str,
                 content_type: str = "application/octet-stream") -> str:
    """
    Upload a Django InMemoryUploadedFile / TemporaryUploadedFile to B2.
    Returns the B2 object key.  Raises on failure.
    """
    from core.views.b2 import upload_fileobj
    return upload_fileobj(file_obj, drop_key, content_type)


def delete_from_b2(drop_key: str) -> bool:
    """Delete a file from B2. Returns True on success or already-gone."""
    from core.views.b2 import delete_object
    return delete_object(drop_key)


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
            db_models.When(file_public_id='', then=free_lifetime_secs),
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