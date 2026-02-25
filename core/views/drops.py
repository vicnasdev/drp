"""
Drop creation, retrieval, and download views.

Password protection:
  - Drops can be password-protected by paid account owners.
  - Web: 401 renders password_prompt.html. On correct password a session
    key is set so the browser isn't re-prompted on refresh.
  - JSON/CLI: 401 returns {"error": "password_required"}. CLI prompts
    interactively via getpass and retries with X-Drop-Password header.
  - The owner is never prompted for their own drop's password.
  - Privacy: wrong password and nonexistent drop both return 401 so
    attackers can't enumerate whether a drop exists.
"""

import secrets
import threading
from datetime import timedelta
from functools import cache

from django.conf import settings
from django.contrib.auth.hashers import check_password as hash_check
from django.http import JsonResponse, HttpResponse, Http404
from django.shortcuts import render, redirect
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.clickjacking import xframe_options_exempt

from core.views.b2 import object_exists, object_size, object_head
from core.views.b2 import object_key as b2_object_key
from core.models import Drop, Plan, SavedDrop
from .helpers import (
    user_plan, max_file_bytes, max_text_bytes, storage_ok,
    is_paid_user, max_lifetime_secs, gen_key, is_valid_drop_key,
    upload_to_b2, delete_from_b2, add_storage, check_password_attempt_rate,
    validate_webhook_url,
)

ANON_COOKIE = "drp_anon"

# Session key prefix for unlocked password-protected drops
_PW_SESSION_PREFIX = "drp_pw_ok:"


def _parse_schedule(value: str):
    """Parse '2h', '30m', '1d' into a datetime offset from now."""
    if not value:
        return None
    value = value.strip().lower()
    try:
        if value.endswith("h"):
            return timezone.now() + timedelta(hours=int(value[:-1]))
        if value.endswith("m"):
            return timezone.now() + timedelta(minutes=int(value[:-1]))
        if value.endswith("d"):
            return timezone.now() + timedelta(days=int(value[:-1]))
        return timezone.now() + timedelta(hours=int(value))
    except (ValueError, OverflowError):
        return None


def _parse_notify(value: str):
    """Parse '7d', '24h' into seconds before expiry."""
    if not value:
        return None
    value = value.strip().lower()
    try:
        if value.endswith("d"):
            return int(value[:-1]) * 86400
        if value.endswith("h"):
            return int(value[:-1]) * 3600
        return int(value) * 86400
    except (ValueError, OverflowError):
        return None


def _fire_webhook(drop):
    """POST to the drop's webhook_url in a background thread. Best-effort."""
    if not drop.webhook_url:
        return
    import requests as http_requests

    def _post():
        try:
            http_requests.post(
                drop.webhook_url,
                json={
                    "event": "drop.accessed",
                    "key": drop.key,
                    "ns": drop.ns,
                    "kind": drop.kind,
                    "view_count": drop.view_count,
                },
                timeout=10,
            )
        except Exception:
            pass

    threading.Thread(target=_post, daemon=True).start()


def _drop_pw_session_key(ns: str, key: str) -> str:
    return f"{_PW_SESSION_PREFIX}{ns}:{key}"


def _is_password_unlocked(request, drop) -> bool:
    """True if this browser session has already authenticated this drop."""
    sk = _drop_pw_session_key(drop.ns, drop.key)
    return request.session.get(sk, False)


def _mark_password_unlocked(request, drop) -> None:
    sk = _drop_pw_session_key(drop.ns, drop.key)
    request.session[sk] = True


def _is_owner(request, drop) -> bool:
    return (
        request.user.is_authenticated
        and drop.owner_id is not None
        and drop.owner_id == request.user.pk
    )


# ── Reserved keys ─────────────────────────────────────────────────────────────

@cache
def _get_reserved_keys():
    from django.urls import get_resolver
    resolver = get_resolver()
    reserved = set()
    for pattern in resolver.url_patterns:
        segment = str(pattern.pattern).strip("^").split("/")[0]
        if segment and not segment.startswith(("(", "?", "<")):
            reserved.add(segment)
    return reserved


# ── Home ──────────────────────────────────────────────────────────────────────

@ensure_csrf_cookie
def home(request):
    claimed = request.session.pop("claimed_drops", 0)
    server_drops = []
    saved_drops = []
    collections = []
    if request.user.is_authenticated:
        server_drops = (
            Drop.objects
            .filter(owner=request.user)
            .order_by("-created_at")[:50]
        )
        saved_drops = (
            SavedDrop.objects
            .filter(user=request.user)
            .order_by("-saved_at")[:50]
        )
        collections = (
            request.user.collections
            .prefetch_related("memberships")
            .order_by("-created_at")[:50]
        )

    # Public feed
    public_drops = (
        Drop.objects
        .filter(is_public=True, burn=False)
        .exclude(password_hash__gt="")
        .select_related("owner")
        .order_by("-created_at")[:20]
    )

    return render(request, "home.html", {
        "server_drops": server_drops,
        "saved_drops": saved_drops,
        "collections": collections,
        "claimed": claimed,
        "public_drops": public_drops,
    })


# ── Public search ─────────────────────────────────────────────────────────────

def public_feed(request):
    """GET /explore/?q=search&tag=python&sort=likes — public drop search/feed."""
    from django.db.models import Q, Count

    q    = request.GET.get("q", "").strip()
    tag  = request.GET.get("tag", "").strip().lower()
    sort = request.GET.get("sort", "").strip().lower()

    qs = (
        Drop.objects
        .filter(is_public=True, burn=False)
        .exclude(password_hash__gt="")
        .select_related("owner")
        .annotate(like_count=Count("likes"))
    )

    if q:
        qs = qs.filter(Q(key__icontains=q) | Q(content__icontains=q) | Q(filename__icontains=q))
    if tag:
        qs = qs.filter(tags__icontains=tag)

    if sort == "likes":
        drops = qs.order_by("-like_count", "-created_at")[:50]
    else:
        drops = qs.order_by("-created_at")[:50]

    # Build set of drop IDs the current user has liked (for toggle state)
    user_liked_ids = set()
    if request.user.is_authenticated:
        drop_ids = [d.pk for d in drops]
        from core.models import DropLike
        user_liked_ids = set(
            DropLike.objects.filter(user=request.user, drop_id__in=drop_ids)
            .values_list("drop_id", flat=True)
        )

    if "application/json" in request.headers.get("Accept", ""):
        return JsonResponse({
            "drops": [
                {
                    "key": d.key,
                    "ns": d.ns,
                    "kind": d.kind,
                    "owner": d.owner.username if d.owner else None,
                    "tags": d.tags,
                    "like_count": d.like_count,
                    "liked": d.pk in user_liked_ids,
                    "created_at": d.created_at.isoformat(),
                    "url": f"/{'f/' if d.ns == 'f' else ''}{d.key}/",
                }
                for d in drops
            ]
        })

    return render(request, "explore.html", {
        "drops": drops,
        "q": q,
        "tag": tag,
        "sort": sort,
        "user_liked_ids": user_liked_ids,
    })


# ── Check key ─────────────────────────────────────────────────────────────────

def check_key(request):
    key = request.GET.get("key", "").strip()
    ns  = request.GET.get("ns", Drop.NS_CLIPBOARD)
    if not key:
        return JsonResponse({"error": "Key required."}, status=400)
    if not is_valid_drop_key(key):
        return JsonResponse({"available": False, "reserved": True, "ns": ns, "key": key})
    if key in _get_reserved_keys():
        return JsonResponse({"available": False, "reserved": True, "ns": ns, "key": key})
    taken = Drop.objects.filter(ns=ns, key=key).exists()
    return JsonResponse({"available": not taken, "ns": ns, "key": key})


# ── Save drop (web flow) ──────────────────────────────────────────────────────

def save_drop(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST required."}, status=405)

    f  = request.FILES.get("file")
    ns = Drop.NS_FILE if f else Drop.NS_CLIPBOARD
    key = request.POST.get("key", "").strip() or gen_key(ns)

    if key in _get_reserved_keys():
        return JsonResponse({"error": f'"{key}" is a reserved key.'}, status=400)

    if not is_valid_drop_key(key):
        return JsonResponse({"error": 'Keys cannot start with "@".'}, status=400)

    existing = Drop.objects.filter(ns=ns, key=key).first()
    if existing and existing.is_expired():
        existing.hard_delete()
        existing = None

    # Allow the original anon uploader to overwrite their own creation-locked drop.
    # The 24-hour lock is meant to block *other* users from hijacking a key,
    # not to prevent the creator from updating their own content.
    anon_token = None
    if not request.user.is_authenticated:
        anon_token = request.COOKIES.get(ANON_COOKIE) or secrets.token_urlsafe(32)

    _anon_owns_existing = (
        existing
        and not request.user.is_authenticated
        and existing.anon_token
        and existing.anon_token == request.COOKIES.get(ANON_COOKIE)
    )

    if existing and not _anon_owns_existing and not existing.can_edit(request.user):
        if existing.is_creation_locked():
            return JsonResponse({
                "error": (
                    "This drop was just created and is protected for 24 hours. "
                    "Wait until the window expires or pick a different key."
                )
            }, status=403)
        return JsonResponse({"error": "This drop is locked to its owner."}, status=403)

    paid = is_paid_user(request.user)

    if f:
        response = _save_file(request, f, ns, key, existing, paid, anon_token)
    else:
        response = _save_text(request, ns, key, existing, paid, anon_token)

    if anon_token and not existing:
        response.set_cookie(
            ANON_COOKIE,
            anon_token,
            max_age=7 * 24 * 3600,
            httponly=True,
            samesite="Lax",
        )

    return response


def _expiry_and_lock(request, paid):
    expires_at   = None
    locked_until = None
    expiry_days  = request.POST.get("expiry_days")

    if paid and expiry_days:
        try:
            days = min(
                int(expiry_days),
                Plan.get(user_plan(request.user), "max_expiry_days"),
            )
            expires_at = timezone.now() + timedelta(days=days)
        except (ValueError, TypeError):
            pass
    elif not request.user.is_authenticated:
        locked_until = timezone.now() + timedelta(hours=24)

    return expires_at, locked_until


def _save_file(request, f, ns, key, existing, paid, anon_token):
    if f.size > max_file_bytes(request.user):
        limit = Plan.get(user_plan(request.user), "max_file_mb")
        return JsonResponse({"error": f"File exceeds {limit} MB limit."}, status=400)

    if not storage_ok(request.user, f.size):
        return JsonResponse({"error": "Storage quota exceeded."}, status=400)

    content_type = f.content_type or "application/octet-stream"

    try:
        b2_key = upload_to_b2(f, ns, key, content_type=content_type)
    except Exception as e:
        return JsonResponse({"error": f"File upload failed: {e}"}, status=500)

    if existing:
        old_size = existing.filesize
        existing.file_public_id = b2_key
        existing.file_url       = ""
        existing.filename       = f.name
        existing.filesize       = f.size
        existing.content_type   = content_type
        existing.save(update_fields=["file_public_id", "file_url", "filename", "filesize", "content_type"])
        from core.views.b2 import invalidate_presigned
        invalidate_presigned(ns, key, filename=f.name)
        if existing.owner_id:
            from django.db import models as db_models
            from core.models import UserProfile
            UserProfile.objects.filter(user_id=existing.owner_id).update(
                storage_used_bytes=db_models.F("storage_used_bytes") + (f.size - old_size)
            )
        drop = existing
    else:
        expires_at, locked_until = _expiry_and_lock(request, paid)
        owner = request.user if request.user.is_authenticated else None
        drop = Drop.objects.create(
            ns=ns, key=key, kind=Drop.FILE,
            file_public_id=b2_key,
            file_url="",
            filename=f.name,
            filesize=f.size,
            content_type=content_type,
            owner=owner,
            locked=paid,
            locked_until=locked_until,
            expires_at=expires_at,
            max_lifetime_secs=max_lifetime_secs(request.user, ns),
            anon_token=anon_token,
        )
        add_storage(request.user, f.size)

    return JsonResponse({
        "key":  drop.key,
        "ns":   drop.ns,
        "kind": drop.kind,
        "url":  f"/f/{drop.key}/",
        "new":  existing is None,
    })


def _save_text(request, ns, key, existing, paid, anon_token):
    text = request.POST.get("content", "").strip()
    if len(text.encode()) > max_text_bytes(request.user):
        limit = Plan.get(user_plan(request.user), "max_text_kb")
        return JsonResponse({"error": f"Text exceeds {limit} KB."}, status=400)

    burn    = request.POST.get("burn") in ("1", "true", "True")
    is_test = request.POST.get("is_test") in ("1", "true", "True")
    webhook_url = request.POST.get("webhook_url", "").strip()
    schedule    = request.POST.get("schedule", "").strip()
    notify      = request.POST.get("notify", "").strip()
    is_public   = request.POST.get("is_public") in ("1", "true", "True")
    tags        = request.POST.get("tags", "").strip()
    source_url  = request.POST.get("source_url", "").strip()

    # Validate webhook URL if provided
    if webhook_url:
        wh_error = validate_webhook_url(webhook_url)
        if wh_error:
            return JsonResponse({"error": f"Invalid webhook URL: {wh_error}"}, status=400)

    if existing:
        existing.content = text
        existing.last_accessed_at = timezone.now()
        existing.save(update_fields=["content", "last_accessed_at"])
        drop = existing
    else:
        expires_at, locked_until = _expiry_and_lock(request, paid)
        # Test-mode drops get a short expiry so cleanup cron handles them,
        # but only when plan logic didn't already compute an explicit expiry.
        if is_test and expires_at is None:
            expires_at = timezone.now() + timedelta(hours=1)
        owner = request.user if request.user.is_authenticated else None

        visible_from = _parse_schedule(schedule) if paid and schedule else None
        # Only allow webhooks for paid users
        wh = webhook_url if (paid and webhook_url) else ""
        notify_secs = _parse_notify(notify) if paid and notify else None

        drop = Drop.objects.create(
            ns=ns, key=key, kind=Drop.TEXT, content=text,
            owner=owner,
            locked=paid,
            locked_until=locked_until,
            expires_at=expires_at,
            max_lifetime_secs=max_lifetime_secs(request.user, ns),
            anon_token=anon_token,
            burn=burn,
            visible_from=visible_from,
            webhook_url=wh,
            notify_before_secs=notify_secs,
            is_public=is_public if request.user.is_authenticated else False,
            tags=tags if request.user.is_authenticated else "",
            source_url=source_url if paid else "",
        )

    # Set password if provided and caller is owner on paid plan
    password = request.POST.get("password", "").strip()
    if password and paid and request.user.is_authenticated and drop.owner_id == request.user.pk:
        drop.set_password(password)
        drop.save(update_fields=["password_hash"])

    return JsonResponse({
        "key":  drop.key,
        "ns":   drop.ns,
        "kind": drop.kind,
        "url":  f"/{drop.key}/",
        "new":  existing is None,
        "burn": drop.burn,
        "password_protected": drop.is_password_protected,
    })


# ── CLI direct-upload endpoints ───────────────────────────────────────────────

def upload_prepare(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST required."}, status=405)

    import json
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON."}, status=400)

    filename     = (data.get("filename") or "").strip()
    size         = int(data.get("size", 0))
    content_type = data.get("content_type") or "application/octet-stream"
    ns           = data.get("ns", Drop.NS_FILE)
    key          = (data.get("key") or "").strip() or gen_key(ns)

    if ns not in (Drop.NS_CLIPBOARD, Drop.NS_FILE):
        return JsonResponse({"error": "Invalid ns."}, status=400)

    if key in _get_reserved_keys():
        return JsonResponse({"error": f'"{key}" is a reserved key.'}, status=400)

    if not is_valid_drop_key(key):
        return JsonResponse({"error": 'Keys cannot start with "@".'}, status=400)

    if size > max_file_bytes(request.user):
        limit = Plan.get(user_plan(request.user), "max_file_mb")
        return JsonResponse({"error": f"File exceeds {limit} MB limit."}, status=413)

    if not storage_ok(request.user, size):
        return JsonResponse({"error": "Storage quota exceeded."}, status=507)

    existing = Drop.objects.filter(ns=ns, key=key).first()
    if existing and existing.is_expired():
        existing.hard_delete()
        existing = None

    if existing and not existing.can_edit(request.user):
        if existing.is_creation_locked():
            return JsonResponse({
                "error": "This drop is protected for 24 hours after creation."
            }, status=403)
        return JsonResponse({"error": "This drop is locked to its owner."}, status=403)

    from core.views.b2 import presigned_put
    EXPIRES_IN = 3600
    presigned_url = presigned_put(ns, key, content_type=content_type,
                                  size=size, expires_in=EXPIRES_IN)

    return JsonResponse({
        "presigned_url": presigned_url,
        "key":           key,
        "ns":            ns,
        "expires_in":    EXPIRES_IN,
    })


def upload_confirm(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST required."}, status=405)

    import json
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON."}, status=400)

    key          = (data.get("key") or "").strip()
    ns           = data.get("ns", Drop.NS_FILE)
    filename     = (data.get("filename") or key).strip()
    content_type = (data.get("content_type") or "application/octet-stream").strip()
    burn         = bool(data.get("burn", False))
    password     = (data.get("password") or "").strip()
    is_test      = bool(data.get("is_test", False))
    webhook_url  = (data.get("webhook_url") or "").strip()
    schedule     = (data.get("schedule") or "").strip()
    notify       = (data.get("notify") or "").strip()
    is_public    = bool(data.get("is_public", False))
    tags         = (data.get("tags") or "").strip()

    # Validate webhook URL if provided
    if webhook_url:
        wh_error = validate_webhook_url(webhook_url)
        if wh_error:
            return JsonResponse({"error": f"Invalid webhook URL: {wh_error}"}, status=400)

    # ── Short expiry for test-mode drops ──────────────────────────────────

    if not key or ns not in (Drop.NS_CLIPBOARD, Drop.NS_FILE):
        return JsonResponse({"error": "key and valid ns required."}, status=400)

    head = object_head(ns, key)
    if head is None:
        return JsonResponse(
            {"error": "File not found in storage. Upload may have failed or expired."},
            status=404,
        )

    actual_size = head["size"]

    if not storage_ok(request.user, actual_size):
        delete_from_b2(ns, key)
        return JsonResponse({"error": "Storage quota exceeded."}, status=507)

    paid = is_paid_user(request.user)

    existing = Drop.objects.filter(ns=ns, key=key).first()
    if existing and existing.is_expired():
        existing.hard_delete()
        existing = None

    if existing:
        old_size = existing.filesize
        existing.file_public_id = b2_object_key(ns, key)
        existing.file_url       = ""
        existing.filename       = filename
        existing.filesize       = actual_size
        existing.content_type   = content_type
        existing.save(update_fields=["file_public_id", "file_url", "filename", "filesize", "content_type"])
        if existing.owner_id:
            from django.db import models as db_models
            from core.models import UserProfile
            UserProfile.objects.filter(user_id=existing.owner_id).update(
                storage_used_bytes=db_models.F("storage_used_bytes") + (actual_size - old_size)
            )
        drop = existing
    else:
        anon_token = None
        if not request.user.is_authenticated:
            anon_token = request.COOKIES.get(ANON_COOKIE) or secrets.token_urlsafe(32)

        expiry_days = data.get("expiry_days")
        expires_at  = None
        locked_until = None
        if paid and expiry_days:
            try:
                days = min(int(expiry_days),
                           Plan.get(user_plan(request.user), "max_expiry_days"))
                expires_at = timezone.now() + timedelta(days=days)
            except (ValueError, TypeError):
                pass
        elif not request.user.is_authenticated:
            locked_until = timezone.now() + timedelta(hours=24)

        # Test-mode drops get a short expiry so cleanup cron handles them,
        # but only when plan logic didn't already compute an explicit expiry.
        if is_test and expires_at is None:
            expires_at = timezone.now() + timedelta(hours=1)

        visible_from = _parse_schedule(schedule) if paid and schedule else None
        wh = webhook_url if paid and webhook_url else ""
        notify_secs = _parse_notify(notify) if paid and notify else None

        owner = request.user if request.user.is_authenticated else None
        drop = Drop.objects.create(
            ns=ns, key=key, kind=Drop.FILE,
            file_public_id=b2_object_key(ns, key),
            file_url="",
            filename=filename,
            filesize=actual_size,
            content_type=content_type,
            owner=owner,
            locked=paid,
            locked_until=locked_until,
            expires_at=expires_at,
            max_lifetime_secs=max_lifetime_secs(request.user, ns),
            anon_token=anon_token,
            burn=burn,
            visible_from=visible_from,
            webhook_url=wh,
            notify_before_secs=notify_secs,
            is_public=is_public if owner else False,
            tags=tags if owner else "",
        )
        add_storage(request.user, actual_size)

    # Set password if provided and caller is owner on paid plan
    if password and paid and request.user.is_authenticated and drop.owner_id == request.user.pk:
        drop.set_password(password)
        drop.save(update_fields=["password_hash"])

    return JsonResponse({
        "key":               drop.key,
        "ns":                drop.ns,
        "kind":              drop.kind,
        "url":               f"/f/{drop.key}/",
        "new":               existing is None,
        "burn":              drop.burn,
        "password_protected": drop.is_password_protected,
    })


# ── Server-side URL upload ────────────────────────────────────────────────────

def upload_from_url(request):
    """
    POST /upload/from-url/
    Server fetches a remote URL and streams the content to B2 on behalf of
    the user.  Avoids the client downloading the file only to re-upload it.

    Requires authentication + Starter/Pro plan.

    Body (JSON):
      url           — the remote URL to fetch (required)
      key           — desired drop key (optional; auto-generated if blank)
      password      — password-protect the drop (optional)
      expiry_days   — custom expiry in days (optional)
      is_test       — short-lived test drop (optional)
      schedule      — delayed visibility, e.g. "2h" (optional, paid)
      webhook_url   — POST on access (optional, paid)
      notify        — email before expiry (optional, paid)
      is_public     — appear in public feed (optional)
      tags          — comma-separated tags (optional)
    """
    if request.method != "POST":
        return JsonResponse({"error": "POST required."}, status=405)

    if not request.user.is_authenticated:
        return JsonResponse({"error": "Login required."}, status=401)

    plan_key = user_plan(request.user)
    if not Plan.get(plan_key, 'remote_upload'):
        return JsonResponse(
            {"error": "Remote URL upload requires a plan with remote upload enabled."},
            status=403,
        )

    import json
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON."}, status=400)

    url = (data.get("url") or "").strip()
    if not url or not (url.startswith("http://") or url.startswith("https://")):
        return JsonResponse({"error": "A valid http(s) URL is required."}, status=400)

    # SSRF check — reuse webhook validator
    ssrf_err = validate_webhook_url(url)
    if ssrf_err:
        return JsonResponse({"error": f"Blocked URL: {ssrf_err}"}, status=400)

    ns  = "f"
    key = (data.get("key") or "").strip() or gen_key(ns)

    if key in _get_reserved_keys():
        return JsonResponse({"error": f'"{key}" is a reserved key.'}, status=400)

    if not is_valid_drop_key(key):
        return JsonResponse({"error": 'Keys cannot start with "@".'}, status=400)

    # ── Fetch the remote URL ──────────────────────────────────────────────
    import requests as _req, io, os.path, mimetypes
    from urllib.parse import urlparse

    try:
        r = _req.get(url, stream=True, timeout=60,
                     headers={"User-Agent": "drp-server/1.0"},
                     allow_redirects=True)
        r.raise_for_status()
    except _req.RequestException as e:
        return JsonResponse({"error": f"Could not fetch URL: {e}"}, status=502)

    content_type = r.headers.get("Content-Type", "application/octet-stream").split(";")[0].strip()
    content_length = int(r.headers.get("Content-Length", 0))

    # Infer filename
    cd = r.headers.get("Content-Disposition", "")
    filename = ""
    if "filename=" in cd:
        for part in cd.split(";"):
            part = part.strip()
            if part.startswith("filename="):
                filename = part[9:].strip("\"'")
                break
    if not filename:
        path = urlparse(url).path.rstrip("/")
        filename = os.path.basename(path) if path else key

    # Size check (if Content-Length reported)
    limit = max_file_bytes(request.user)
    if content_length and content_length > limit:
        r.close()
        limit_mb = Plan.get(user_plan(request.user), "max_file_mb")
        return JsonResponse({"error": f"Remote file exceeds {limit_mb} MB limit."}, status=413)

    # Stream into an in-memory buffer (capped at plan limit)
    buf = io.BytesIO()
    total = 0
    try:
        for chunk in r.iter_content(chunk_size=256 * 1024):
            if chunk:
                total += len(chunk)
                if total > limit:
                    r.close()
                    buf.close()
                    limit_mb = Plan.get(user_plan(request.user), "max_file_mb")
                    return JsonResponse(
                        {"error": f"Remote file exceeds {limit_mb} MB limit."},
                        status=413,
                    )
                buf.write(chunk)
    except _req.RequestException as e:
        buf.close()
        return JsonResponse({"error": f"Download interrupted: {e}"}, status=502)
    finally:
        r.close()

    if not storage_ok(request.user, total):
        buf.close()
        return JsonResponse({"error": "Storage quota exceeded."}, status=507)

    # ── Handle existing drop ──────────────────────────────────────────────
    existing = Drop.objects.filter(ns=ns, key=key).first()
    if existing and existing.is_expired():
        existing.hard_delete()
        existing = None

    if existing and not existing.can_edit(request.user):
        buf.close()
        if existing.is_creation_locked():
            return JsonResponse(
                {"error": "This drop is protected for 24 hours after creation."},
                status=403,
            )
        return JsonResponse({"error": "This drop is locked to its owner."}, status=403)

    # ── Upload to B2 ─────────────────────────────────────────────────────
    buf.seek(0)
    upload_to_b2(buf, ns, key, content_type)
    buf.close()

    paid = is_paid_user(request.user)

    password     = (data.get("password") or "").strip()
    is_test      = bool(data.get("is_test", False))
    webhook_url  = (data.get("webhook_url") or "").strip()
    schedule     = (data.get("schedule") or "").strip()
    notify       = (data.get("notify") or "").strip()
    is_public    = bool(data.get("is_public", False))
    tags         = (data.get("tags") or "").strip()

    if webhook_url:
        wh_error = validate_webhook_url(webhook_url)
        if wh_error:
            return JsonResponse({"error": f"Invalid webhook URL: {wh_error}"}, status=400)

    if existing:
        old_size = existing.filesize
        existing.file_public_id = b2_object_key(ns, key)
        existing.file_url       = ""
        existing.filename       = filename
        existing.filesize       = total
        existing.content_type   = content_type
        existing.save(update_fields=[
            "file_public_id", "file_url", "filename", "filesize", "content_type",
        ])
        if existing.owner_id:
            from django.db import models as db_models
            from core.models import UserProfile
            UserProfile.objects.filter(user_id=existing.owner_id).update(
                storage_used_bytes=db_models.F("storage_used_bytes") + (total - old_size)
            )
        drop = existing
    else:
        expiry_days = data.get("expiry_days")
        expires_at = None
        if paid and expiry_days:
            try:
                days = min(int(expiry_days),
                           Plan.get(user_plan(request.user), "max_expiry_days"))
                expires_at = timezone.now() + timedelta(days=days)
            except (ValueError, TypeError):
                pass

        if is_test and expires_at is None:
            expires_at = timezone.now() + timedelta(hours=1)

        visible_from = _parse_schedule(schedule) if paid and schedule else None
        wh = webhook_url if paid and webhook_url else ""
        notify_secs = _parse_notify(notify) if paid and notify else None

        drop = Drop.objects.create(
            ns=ns, key=key, kind=Drop.FILE,
            file_public_id=b2_object_key(ns, key),
            file_url="",
            filename=filename,
            filesize=total,
            content_type=content_type,
            owner=request.user,
            locked=paid,
            expires_at=expires_at,
            max_lifetime_secs=max_lifetime_secs(request.user, ns),
            burn=False,
            visible_from=visible_from,
            webhook_url=wh,
            notify_before_secs=notify_secs,
            is_public=is_public,
            tags=tags if is_public else "",
        )
        add_storage(request.user, total)

    if password and paid and drop.owner_id == request.user.pk:
        drop.set_password(password)
        drop.save(update_fields=["password_hash"])

    return JsonResponse({
        "key":               drop.key,
        "ns":                drop.ns,
        "kind":              drop.kind,
        "url":               f"/f/{drop.key}/",
        "filename":          drop.filename,
        "filesize":          drop.filesize,
        "new":               existing is None,
        "password_protected": drop.is_password_protected,
    })


# ── Password gate helpers ─────────────────────────────────────────────────────

def _password_required_response(request, drop):
    """
    Return the appropriate 401 response when a password is needed.
    JSON clients get {"error": "password_required"}.
    Browser clients get a minimal password prompt page.
    Never reveals whether the drop exists to unauthenticated requesters.
    """
    if "application/json" in request.headers.get("Accept", ""):
        return JsonResponse(
            {"error": "password_required", "key": drop.key, "ns": drop.ns},
            status=401,
        )
    return render(request, "password_prompt.html", {
        "drop": drop,
        "next": request.get_full_path(),
    }, status=401)


def _check_drop_password(request, drop):
    """
    Returns None if access is granted, or a 401 response if not.
    Access is granted when:
      - Drop has no password
      - Requester is the owner
      - Browser session already unlocked this drop
      - Correct password supplied via X-Drop-Password header (CLI) or POST
    
    Rate limits password attempts (10 per IP per drop per hour) to prevent brute forcing.
    """
    if not drop.is_password_protected:
        return None

    if _is_owner(request, drop):
        return None

    if _is_password_unlocked(request, drop):
        return None

    # CLI / JSON path: password in header
    header_pw = request.headers.get("X-Drop-Password", "")
    if header_pw:
        allowed, remaining = check_password_attempt_rate(request, drop.key, drop.ns)
        if not allowed:
            return JsonResponse({"error": "Too many password attempts. Try again later."}, status=429)
        if drop.check_password(header_pw):
            return None

    # Web POST path: password submitted via prompt form
    if request.method == "POST":
        form_pw = request.POST.get("drop_password", "")
        if form_pw:
            allowed, remaining = check_password_attempt_rate(request, drop.key, drop.ns)
            if not allowed:
                return JsonResponse({"error": "Too many password attempts. Try again later."}, status=429)
            if drop.check_password(form_pw):
                _mark_password_unlocked(request, drop)
                return None

    return _password_required_response(request, drop)


# ── View drop ─────────────────────────────────────────────────────────────────

def _drop_response(request, drop):
    if drop.is_expired():
        drop.hard_delete()
        if "application/json" in request.headers.get("Accept", ""):
            return JsonResponse({"error": "Drop has expired."}, status=410)
        return render(request, "expired.html", {"key": drop.key})

    # Scheduled drops — pending until visible_from
    if not drop.is_visible and not _is_owner(request, drop):
        if "application/json" in request.headers.get("Accept", ""):
            return JsonResponse({"error": "This drop is not yet available."}, status=403)
        raise Http404

    # Password gate — owner bypasses automatically
    pw_response = _check_drop_password(request, drop)
    if pw_response is not None:
        return pw_response

    should_burn = drop.burn
    drop.touch()
    _fire_webhook(drop)

    if "application/json" in request.headers.get("Accept", ""):
        data = {
            "key":               drop.key,
            "ns":                drop.ns,
            "kind":              drop.kind,
            "burn":              drop.burn,
            "password_protected": drop.is_password_protected,
            "created_at":        drop.created_at.isoformat(),
            "last_accessed_at":  (drop.last_accessed_at.isoformat()
                                  if drop.last_accessed_at else None),
            "expires_at":        (drop.expires_at.isoformat()
                                  if drop.expires_at else None),
            "view_count":        drop.view_count,
            "last_viewed_at":    (drop.last_viewed_at.isoformat()
                                  if drop.last_viewed_at else None),
            "is_public":         drop.is_public,
            "tags":              drop.tags,
            "like_count":        drop.likes.count(),
        }
        if drop.kind == Drop.TEXT:
            # Live API reference — fetch fresh content from source_url
            if drop.source_url:
                import requests as _req
                try:
                    r = _req.get(drop.source_url, timeout=15,
                                 headers={'User-Agent': 'drp/live-fetch'})
                    r.raise_for_status()
                    live_content = r.text
                except Exception as exc:
                    data["source_url"] = drop.source_url
                    data["fetch_error"] = str(exc)
                    live_content = None
                if live_content is not None:
                    data["content"] = live_content
                    data["source_url"] = drop.source_url
                    if request.GET.get("parse") == "1":
                        from cli.smart_parse import smart_parse, dot_access
                        fmt, parsed = smart_parse(live_content)
                        data["content_format"] = fmt
                        data["parsed"] = parsed
                        field = request.GET.get("field", "").strip()
                        if field:
                            try:
                                data["field_value"] = dot_access(parsed, field)
                            except (KeyError, TypeError):
                                data["field_error"] = f"Field '{field}' not found."
            else:
                data["content"] = drop.content
                # Auto-detect content format for smart clients
                if request.GET.get("parse") == "1":
                    from cli.smart_parse import smart_parse, dot_access
                    fmt, parsed = smart_parse(drop.content)
                    data["content_format"] = fmt
                    data["parsed"] = parsed
                    field = request.GET.get("field", "").strip()
                    if field:
                        try:
                            data["field_value"] = dot_access(parsed, field)
                        except (KeyError, TypeError):
                            data["field_error"] = f"Field '{field}' not found."
        else:
            data["filename"] = drop.filename
            data["filesize"]  = drop.filesize
            data["download"] = f"/f/{drop.key}/download/"
            try:
                data["presigned_url"] = drop.download_url(expires_in=3600)
            except Exception:
                pass

        response = JsonResponse(data)
        if should_burn:
            drop.hard_delete()
        return response

    plan = user_plan(request.user)
    is_owner = _is_owner(request, drop)
    response = render(request, "drop.html", {
        "drop":            drop,
        "can_edit":        drop.can_edit(request.user),
        "is_owner":        is_owner,
        "is_paid_owner":   is_owner and request.user.profile.is_paid,
        "max_expiry_days": Plan.get(plan, "max_expiry_days"),
    })

    if should_burn:
        drop.hard_delete()

    return response


def clipboard_view(request, key):
    # Handle password prompt POST
    if request.method == "POST" and "drop_password" in request.POST:
        drop = Drop.objects.filter(ns=Drop.NS_CLIPBOARD, key=key).first()
        if not drop:
            raise Http404
        return _drop_response(request, drop)

    drop = Drop.objects.filter(ns=Drop.NS_CLIPBOARD, key=key).first()
    if not drop:
        if "application/json" in request.headers.get("Accept", ""):
            return JsonResponse({"error": "Drop not found."}, status=404)
        raise Http404
    return _drop_response(request, drop)


def file_view(request, key):
    # Handle password prompt POST
    if request.method == "POST" and "drop_password" in request.POST:
        drop = Drop.objects.filter(ns=Drop.NS_FILE, key=key).first()
        if not drop:
            raise Http404
        return _drop_response(request, drop)

    drop = Drop.objects.filter(ns=Drop.NS_FILE, key=key).first()
    if not drop:
        if "application/json" in request.headers.get("Accept", ""):
            return JsonResponse({"error": "Drop not found."}, status=404)
        raise Http404
    return _drop_response(request, drop)


# ── Raw text view ─────────────────────────────────────────────────────────────

def raw_view(request, key):
    drop = Drop.objects.filter(ns=Drop.NS_CLIPBOARD, key=key).first()
    if not drop:
        return HttpResponse("not found\n", content_type="text/plain", status=404)

    if drop.is_expired():
        drop.hard_delete()
        return HttpResponse("expired\n", content_type="text/plain", status=410)

    if drop.kind != Drop.TEXT:
        return HttpResponse(
            "file drops cannot be fetched as raw text\n",
            content_type="text/plain",
            status=400,
        )

    # Password gate for raw view — header only (no browser prompt)
    if drop.is_password_protected and not _is_owner(request, drop):
        header_pw = request.headers.get("X-Drop-Password", "")
        if not header_pw or not drop.check_password(header_pw):
            return HttpResponse(
                "password required\n", content_type="text/plain", status=401
            )

    should_burn = drop.burn
    drop.touch()
    response = HttpResponse(drop.content, content_type="text/plain; charset=utf-8")
    if should_burn:
        drop.hard_delete()
    return response


# ── Download ──────────────────────────────────────────────────────────────────

def raw_file(request, key):
    """Stream file content through Django for in-browser rendering (avoids B2 CORS)."""
    drop = Drop.objects.filter(ns=Drop.NS_FILE, key=key).first()
    if not drop:
        raise Http404
    if drop.is_expired():
        drop.hard_delete()
        raise Http404

    if drop.is_password_protected and not _is_owner(request, drop):
        if not _is_password_unlocked(request, drop):
            header_pw = request.headers.get("X-Drop-Password", "")
            if not header_pw or not drop.check_password(header_pw):
                return JsonResponse({"error": "password_required"}, status=401)

    try:
        import requests as http_requests
        url = drop.download_url(expires_in=300)
        upstream = http_requests.get(url, timeout=15)
        upstream.raise_for_status()
    except Exception:
        raise Http404

    content_type = drop.content_type or "application/octet-stream"
    return HttpResponse(upstream.content, content_type=content_type)


def download_drop(request, key):
    drop = Drop.objects.filter(ns=Drop.NS_FILE, key=key).first()
    if not drop:
        raise Http404
    if drop.is_expired():
        drop.hard_delete()
        raise Http404

    # Password gate for download
    if drop.is_password_protected and not _is_owner(request, drop):
        if not _is_password_unlocked(request, drop):
            header_pw = request.headers.get("X-Drop-Password", "")
            if not header_pw or not drop.check_password(header_pw):
                if "application/json" in request.headers.get("Accept", ""):
                    return JsonResponse({"error": "password_required"}, status=401)
                return render(request, "password_prompt.html", {
                    "drop": drop,
                    "next": request.get_full_path(),
                }, status=401)

    drop.touch()
    try:
        url = drop.download_url(expires_in=3600)
    except Exception as e:
        import logging
        logging.error(f"Error in download view for drop {key}: {e}")
        raise Http404
    return redirect(url)


# ── Set / remove drop password ────────────────────────────────────────────────

def set_drop_password(request, ns, key):
    """
    POST /key/set-password/ or /f/key/set-password/

    Paid owners only. Body (JSON):
      {"password": "new-password"}   — set/change password
      {"password": ""}               — remove password
    """
    if request.method != "POST":
        return JsonResponse({"error": "POST required."}, status=405)

    drop = Drop.objects.filter(ns=ns, key=key).first()
    if not drop:
        return JsonResponse({"error": "Drop not found."}, status=404)

    if not _is_owner(request, drop):
        return JsonResponse({"error": "Only the owner can set a password."}, status=403)

    if not hasattr(request.user, "profile") or not request.user.profile.is_paid:
        return JsonResponse(
            {"error": "Password protection is a paid feature."}, status=403
        )

    import json
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON."}, status=400)

    password = (data.get("password") or "").strip()
    drop.set_password(password if password else None)
    drop.save(update_fields=["password_hash"])

    return JsonResponse({
        "password_protected": drop.is_password_protected,
        "message": "Password set." if drop.is_password_protected else "Password removed.",
    })


# ── Embed view ────────────────────────────────────────────────────────────────

@xframe_options_exempt
def embed_view(request, key):
    """
    GET /embed/<key>/ — minimal iframe-friendly view for text/code/image drops.
    No chrome, no nav, no edit controls. Read-only.
    """
    # Try clipboard first, then file
    drop = Drop.objects.filter(ns=Drop.NS_CLIPBOARD, key=key).first()
    ns = "c"
    if not drop:
        drop = Drop.objects.filter(ns=Drop.NS_FILE, key=key).first()
        ns = "f"
    if not drop:
        return HttpResponse("not found", status=404, content_type="text/plain")
    if drop.is_expired():
        drop.hard_delete()
        return HttpResponse("expired", status=410, content_type="text/plain")
    if drop.is_password_protected:
        return HttpResponse("password protected", status=401, content_type="text/plain")
    if not drop.is_visible:
        return HttpResponse("not yet available", status=403, content_type="text/plain")

    drop.touch()

    return render(request, "embed.html", {
        "drop": drop,
        "ns": ns,
    })