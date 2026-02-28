"""
core/api/views.py
"""
from __future__ import annotations

import json

from django.contrib.auth import authenticate
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from core.api.auth import token_required, issue_token, revoke_token
from core.models import File, Folder, FolderItem, APIToken, UserProfile, PLAN_LIMITS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _json(data, status=200):
    return JsonResponse(data, status=status)

def _err(msg, status=400):
    return JsonResponse({"error": msg}, status=status)

def _body(request):
    try:
        return json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return {}

def _profile(user):
    try:
        return user.profile
    except UserProfile.DoesNotExist:
        return None

def _fmt_size(b):
    for unit in ("B", "KB", "MB", "GB"):
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} TB"


# ---------------------------------------------------------------------------
# Ping
# ---------------------------------------------------------------------------

def ping(request):
    return _json({"status": "ok", "version": "1.0.0", "latency_ms": 0})


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

@csrf_exempt
@require_http_methods(["POST"])
def auth_login(request):
    data     = _body(request)
    username = data.get("username", "")
    password = data.get("password", "")
    user     = authenticate(request, username=username, password=password)
    if user is None:
        return _err("invalid credentials", 401)
    token_obj, raw = issue_token(user)
    return _json({"token": raw, "username": user.username})


@csrf_exempt
@require_http_methods(["POST"])
@token_required
def auth_logout(request):
    revoke_token(request.auth_token)
    return _json({"status": "ok"})


@require_http_methods(["GET"])
@token_required
def auth_me(request):
    user    = request.user
    profile = _profile(user)
    plan    = profile.plan if profile else "free"
    limits  = PLAN_LIMITS.get(plan, {})
    used    = profile.storage_used_bytes if profile else 0
    quota   = limits.get("storage_gb", 0) * 1024 ** 3
    return _json({
        "username":              user.username,
        "email":                 user.email,
        "plan":                  plan,
        "storage_used_display":  _fmt_size(used),
        "storage_quota_display": f"{limits.get('storage_gb', 0)} GB",
        "drop_count":            File.objects.filter(owner=user).count(),
        "folder_count":          Folder.objects.filter(owner=user).count(),
    })


# ---------------------------------------------------------------------------
# Files (drops)
# ---------------------------------------------------------------------------

@csrf_exempt
@require_http_methods(["GET", "POST"])
def files_list_or_upload(request):
    # FIX: GET handler added so authenticated users can list their own drops.
    # Shell `ls` at root calls this to show loose drops (not in any folder)
    # alongside folders. Previously only POST existed, so shell ls was always empty.
    if request.method == "GET":
        if not request.user.is_authenticated:
            return _err("authentication required", 401)
        from core.storage import b2_download_url
        drops = File.objects.filter(owner=request.user).order_by("-created_at")[:100]
        return _json({
            "items": [
                {
                    "key":          f.key,
                    "filename":     f.filename,
                    "size":         f.size,
                    "size_display": _fmt_size(f.size),
                    "content_type": f.content_type,
                    "expires_at":   f.expires_at.isoformat() if f.expires_at else None,
                    "is_public":    f.is_public,
                    "download_url": b2_download_url(f.b2_name),
                }
                for f in drops
            ]
        })
    import re
    import mimetypes
    from datetime import timedelta
    from django.utils import timezone
    from core.models import ANON_MAX_FILE_MB, ANON_LIFETIME_DAYS, generate_key
    from core.storage import b2_upload, b2_upload_text

    user    = request.user if request.user.is_authenticated else None
    profile = _profile(user) if user else None
    max_mb  = profile.plan_limits["max_file_mb"] if profile else ANON_MAX_FILE_MB

    uploaded = request.FILES.get("file")
    if not uploaded:
        return _err("no file provided")

    if uploaded.size > max_mb * 1024 * 1024:
        return _err(f"file too large — max {max_mb} MB", 413)

    if profile and not profile.has_storage_for(uploaded.size):
        return _err("storage quota exceeded", 413)

    custom_key  = (request.POST.get("key") or "").strip()
    burn        = request.POST.get("burn") == "true"
    public      = request.POST.get("public") == "true"
    expires_raw = request.POST.get("expires")
    folder_id   = request.POST.get("folder_id")
    password    = request.POST.get("password")

    # validate custom key
    if custom_key:
        if not re.match(r'^[a-zA-Z0-9_\-]{1,64}$', custom_key):
            return _err("invalid key format")
        existing = File.objects.filter(key=custom_key).first()
        if existing and existing.owner != user:
            return _err("key already taken", 409)

    # expiry
    if user and profile:
        limits   = profile.plan_limits
        max_days = limits["max_expiry_days"]
        if expires_raw:
            # parse e.g. "7d", "24h"
            match = re.match(r'(\d+)([dh])', expires_raw)
            if match:
                n, unit = int(match.group(1)), match.group(2)
                days = n if unit == "d" else n / 24
            else:
                days = max_days
        else:
            days = max_days
        days       = min(days, max_days)
        expires_at = timezone.now() + timedelta(days=days)
    else:
        expires_at = timezone.now() + timedelta(days=ANON_LIFETIME_DAYS)

    # upload to B2
    try:
        ct       = uploaded.content_type or mimetypes.guess_type(uploaded.name)[0] or "application/octet-stream"
        b2_name, size = b2_upload(uploaded, uploaded.name, ct)
        filename = uploaded.name
    except Exception:
        return _err("upload failed", 500)

    # password hash
    import hashlib
    pw_hash = hashlib.sha256(password.encode()).hexdigest() if password else ""

    # create File record
    drop = File.objects.create(
        key           = custom_key or generate_key(),
        owner         = user,
        anon_token    = "" if user else "",
        b2_name       = b2_name,
        filename      = filename,
        content_type  = ct,
        size          = size,
        expires_at    = expires_at,
        is_public     = public if user else False,
        burn_after_read = burn,
        password_hash = pw_hash,
    )

    # add to folder
    if folder_id:
        try:
            from core.models import Folder, FolderItem
            folder = Folder.objects.get(id=int(folder_id), owner=user)
            FolderItem.objects.get_or_create(folder=folder, key=drop.key, defaults={"label": filename})
        except (Folder.DoesNotExist, ValueError):
            pass

    # update storage
    if profile:
        UserProfile.objects.filter(user=user).update(
            storage_used_bytes=profile.storage_used_bytes + size
        )

    return _json({
        "key":        drop.key,
        "filename":   drop.filename,
        "size":       drop.size,
        "expires_at": drop.expires_at.isoformat() if drop.expires_at else None,
        "content_type": drop.content_type,
    }, status=201)


@csrf_exempt
@require_http_methods(["GET", "PATCH", "DELETE"])
def files_detail(request, key):
    try:
        f = File.objects.get(key=key)
    except File.DoesNotExist:
        return _err("not found", 404)

    if request.method == "GET":
        from core.storage import b2_download_url  # FIX: generate a presigned download URL
        return _json({
            "key":             f.key,
            "filename":        f.filename,
            "size":            f.size,
            "size_display":    _fmt_size(f.size),
            "content_type":    f.content_type,
            "expires_at":      f.expires_at.isoformat() if f.expires_at else None,
            "is_public":       f.is_public,
            "is_encrypted":    False,
            "burn_after_read": f.burn_after_read,
            "view_count":      f.view_count,
            "created_at":      f.created_at.isoformat(),
            "download_url":    b2_download_url(f.b2_name),  # FIX: was missing — caused KeyError in CLI
        })

    if request.method == "PATCH":
        if not request.user.is_authenticated or f.owner != request.user:
            return _err("permission denied", 403)
        data    = _body(request)
        new_key = data.get("key")
        if new_key:
            if File.objects.filter(key=new_key).exclude(pk=f.pk).exists():
                return _err("key already taken", 409)
            f.key = new_key
        for field in ("is_public", "burn_after_read", "expires_at"):
            if field in data:
                setattr(f, field, data[field])
        f.save()
        return _json({"key": f.key})

    if request.method == "DELETE":
        if not request.user.is_authenticated or f.owner != request.user:
            return _err("permission denied", 403)
        f.delete()
        return _json({"status": "ok"})


@csrf_exempt
@require_http_methods(["POST"])
@token_required
def files_fork(request, key):
    return _err("not implemented", 501)


# ---------------------------------------------------------------------------
# Folders
# ---------------------------------------------------------------------------

def _folder_data(folder):
    items = [
        {
            "key":          fi.key,
            "filename":     fi.label or fi.key,
            "label":        fi.label,
        }
        for fi in folder.items.all()
    ]
    subfolders = [
        {"id": c.id, "slug": c.slug, "is_public": c.is_public}
        for c in folder.children.all()
    ]
    return {
        "id":        folder.id,
        "slug":      folder.slug,
        "is_public": folder.is_public,
        "items":     items,
        "folders":   subfolders,
    }


@csrf_exempt
@require_http_methods(["GET", "POST"])
@token_required
def folders_list_create(request):
    if request.method == "GET":
        folders = Folder.objects.filter(owner=request.user, parent=None)
        return _json({
            "items":   [],
            "folders": [{"id": f.id, "slug": f.slug, "is_public": f.is_public} for f in folders],
        })

    data      = _body(request)
    slug      = data.get("slug", "").strip()
    parent_id = data.get("parent_id")
    public    = data.get("public", False)

    if not slug:
        return _err("slug is required")

    parent = None
    if parent_id:
        try:
            parent = Folder.objects.get(id=parent_id, owner=request.user)
        except Folder.DoesNotExist:
            return _err("parent folder not found", 404)

    if Folder.objects.filter(owner=request.user, parent=parent, slug=slug).exists():
        return _err("folder already exists", 409)

    folder = Folder.objects.create(owner=request.user, slug=slug, parent=parent, is_public=public)
    return _json({"id": folder.id, "slug": folder.slug}, status=201)


@csrf_exempt
@require_http_methods(["GET", "PATCH", "DELETE"])
@token_required
def folders_detail(request, folder_id):
    try:
        folder = Folder.objects.get(id=folder_id, owner=request.user)
    except Folder.DoesNotExist:
        return _err("not found", 404)

    if request.method == "GET":
        return _json(_folder_data(folder))

    if request.method == "PATCH":
        data = _body(request)
        if "slug" in data:
            folder.slug = data["slug"]
        if "parent_id" in data:
            pid = data["parent_id"]
            if pid is None:
                folder.parent = None
            else:
                try:
                    folder.parent = Folder.objects.get(id=pid, owner=request.user)
                except Folder.DoesNotExist:
                    return _err("parent not found", 404)
        if "public" in data:
            folder.is_public = data["public"]
        folder.save()
        return _json({"id": folder.id, "slug": folder.slug})

    if request.method == "DELETE":
        recursive = request.GET.get("recursive", "false").lower() == "true"
        if not recursive and (folder.children.exists() or folder.items.exists()):
            return _err("folder is not empty — use recursive=true", 409)
        folder.delete()
        return _json({"status": "ok"})


# ---------------------------------------------------------------------------
# Path resolver
# ---------------------------------------------------------------------------

@require_http_methods(["GET"])
@token_required
def resolve(request):
    path = request.GET.get("path", "").strip("/")
    # expected: @username/slug or @username/slug/subslug
    parts = path.lstrip("@").split("/")
    if len(parts) < 2:
        return _err("invalid path")
    from django.contrib.auth import get_user_model
    User = get_user_model()
    try:
        user = User.objects.get(username=parts[0])
    except User.DoesNotExist:
        return _err("user not found", 404)
    try:
        folder = Folder.objects.get(owner=user, slug=parts[1], parent=None)
        for part in parts[2:]:
            folder = folder.children.get(slug=part)
    except Folder.DoesNotExist:
        return _err("not found", 404)
    return _json({"type": "folder", "object": _folder_data(folder)})


# ---------------------------------------------------------------------------
# Share tokens
# ---------------------------------------------------------------------------

@csrf_exempt
@require_http_methods(["GET", "POST"])
@token_required
def share_list_create(request):
    return _json({"results": []})


@csrf_exempt
@require_http_methods(["DELETE"])
@token_required
def share_detail(request, token_id):
    return _err("not implemented", 501)


# ---------------------------------------------------------------------------
# API tokens
# ---------------------------------------------------------------------------

@csrf_exempt
@require_http_methods(["GET", "POST"])
@token_required
def tokens_list_create(request):
    if request.method == "GET":
        tokens = APIToken.objects.filter(user=request.user).values("id", "label", "last_used", "created_at")
        return _json({"results": list(tokens)})
    data      = _body(request)
    label     = data.get("label", "")
    token_obj, raw = issue_token(request.user, label=label)
    return _json({"id": token_obj.id, "token": raw, "label": label}, status=201)


@csrf_exempt
@require_http_methods(["DELETE"])
@token_required
def tokens_detail(request, token_id):
    try:
        token = APIToken.objects.get(id=token_id, user=request.user)
    except APIToken.DoesNotExist:
        return _err("not found", 404)
    token.delete()
    return _json({"status": "ok"})


# ---------------------------------------------------------------------------
# Crash reporting
# FIX: this endpoint was missing entirely. The CLI posts here after every
# unhandled exception, but was getting 404s, so CrashReport records were
# never created and GitHub issues were never filed. The route is now wired
# in urls.py and delegates to the existing error_reporting_logic module
# which handles deduplication and GitHub issue creation.
# ---------------------------------------------------------------------------

@csrf_exempt
@require_http_methods(["POST"])
def crash_report(request):
    from threading import Thread
    from core.error_reporting_logic import maybe_file_issue

    data = _body(request)
    if not data:
        return _err("no data", 400)

    # Normalise the payload from the CLI into what maybe_file_issue expects.
    # CLI sends: fingerprint, exc_type, title, traceback (str), cli_version.
    # maybe_file_issue expects: exc_type, exc_message, traceback (list), cli_version.
    normalised = {
        "exc_type":       data.get("exc_type", "UnknownError"),
        "exc_message":    data.get("title", ""),
        "traceback":      [data.get("traceback", "")],
        "cli_version":    data.get("cli_version", ""),
        "command":        data.get("command", ""),
        "python_version": data.get("python_version", ""),
        "platform":       data.get("platform", ""),
    }

    # Fire-and-forget in a daemon thread — same pattern as the CLI sender —
    # so the response returns immediately and the CLI isn't kept waiting.
    Thread(target=maybe_file_issue, args=(normalised,), daemon=True).start()

    return _json({"status": "ok"}, status=202)