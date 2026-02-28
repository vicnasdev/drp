"""
core/views/drop.py

All drop-level actions: save, view, delete, rename, raw, download, embed,
like, bookmark, set-password, check-key.
"""

import csv
import hashlib
import mimetypes
import re
import secrets
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.http import (
    HttpResponse, JsonResponse, Http404, HttpResponseRedirect,
)
from django.shortcuts import get_object_or_404, render, redirect
from django.utils import timezone
from django.views.decorators.http import require_POST, require_GET
from django.views.decorators.csrf import csrf_exempt

from core.models import (
    File, FileBookmark, Like, UserProfile, Folder, FolderItem,
    FREE_LIFETIME_DAYS, ANON_LIFETIME_DAYS, ANON_MAX_FILE_MB, PLAN_LIMITS,
)
from core.storage import (
    b2_upload, b2_upload_text, b2_download_url, b2_read, b2_delete,
)

import logging
logger = logging.getLogger(__name__)

SESSION_ANON_KEY = "anon_token"
PASSWORD_SESSION_PREFIX = "drop_pw_unlocked_"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_anon_token(request) -> str:
    if SESSION_ANON_KEY not in request.session:
        request.session[SESSION_ANON_KEY] = secrets.token_hex(16)
    return request.session[SESSION_ANON_KEY]


def _get_client_ip(request) -> str:
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return xff.split(",")[0].strip() if xff else request.META.get("REMOTE_ADDR", "")


def _can_edit(request, drop: File) -> bool:
    """Owner can always edit. Anon can edit if anon_token matches and not locked."""
    if drop.is_locked:
        return request.user.is_authenticated and drop.owner == request.user
    if request.user.is_authenticated:
        return drop.owner == request.user
    token = request.session.get(SESSION_ANON_KEY)
    return bool(token and drop.anon_token == token)


def _check_password(request, drop: File) -> bool:
    """Return True if password is not required or already unlocked."""
    if not drop.is_password_protected:
        return True
    session_key = f"{PASSWORD_SESSION_PREFIX}{drop.key}"
    return request.session.get(session_key, False)


def _hash_password(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()


def _expiry_for_user(request, expiry_days=None) -> timezone.datetime | None:
    """Compute expires_at based on plan and requested expiry."""
    if request.user.is_authenticated:
        profile = request.user.profile
        limits  = profile.plan_limits
        max_days = limits["max_expiry_days"]
        days = min(int(expiry_days or max_days), max_days)
        return timezone.now() + timedelta(days=days)
    else:
        return timezone.now() + timedelta(days=ANON_LIFETIME_DAYS)


# ── Content type sniffing ─────────────────────────────────────────────────────

def _sniff_content_type(text: str) -> tuple[str, str]:
    """Infer (content_type, extension) from pasted text content."""
    stripped = text.strip()

    # JSON
    try:
        import json as _json
        _json.loads(stripped)
        return "application/json", ".json"
    except (ValueError, MemoryError):
        pass

    # SVG
    if stripped.startswith("<svg") or (stripped.startswith("<?xml") and "<svg" in stripped[:512]):
        return "image/svg+xml", ".svg"

    # XML
    if stripped.startswith("<?xml") or (stripped.startswith("<") and re.match(r'<\w[\w:.-]*[\s>]', stripped)):
        if re.match(r'^\s*<!DOCTYPE html|<html', stripped, re.IGNORECASE):
            return "text/html", ".html"
        return "application/xml", ".xml"

    # HTML
    if re.match(r'^\s*<!DOCTYPE html|^\s*<html', stripped, re.IGNORECASE):
        return "text/html", ".html"

    # CSV / TSV
    try:
        dialect = csv.Sniffer().sniff(stripped[:4096], delimiters=",\t;|")
        if csv.Sniffer().has_header(stripped[:4096]):
            ext = ".tsv" if dialect.delimiter == "\t" else ".csv"
            return "text/csv", ext
    except csv.Error:
        pass

    # Markdown (heuristic)
    md_score = sum([
        bool(re.search(r'^#{1,6} ', stripped, re.MULTILINE)),
        bool(re.search(r'\*\*.+\*\*', stripped)),
        bool(re.search(r'```', stripped)),
        bool(re.search(r'^\s*[-*] ', stripped, re.MULTILINE)),
        bool(re.search(r'\[.+\]\(.+\)', stripped)),
        bool(re.search(r'^---\s*$', stripped, re.MULTILINE)),
    ])
    if md_score >= 2:
        return "text/markdown", ".md"

    # Code via pygments
    try:
        from pygments.lexers import guess_lexer
        from pygments.util import ClassNotFound
        lexer = guess_lexer(stripped)
        EXT_MAP = {
            "Python":       ("text/x-python",          ".py"),
            "JavaScript":   ("application/javascript",  ".js"),
            "TypeScript":   ("text/x-typescript",       ".ts"),
            "Rust":         ("text/x-rustsrc",          ".rs"),
            "Go":           ("text/x-go",               ".go"),
            "Bash":         ("application/x-sh",        ".sh"),
            "SQL":          ("application/sql",         ".sql"),
            "YAML":         ("text/yaml",               ".yaml"),
            "TOML":         ("application/toml",        ".toml"),
            "Dockerfile":   ("text/x-dockerfile",       ".dockerfile"),
            "Diff":         ("text/x-diff",             ".diff"),
            "CSS":          ("text/css",                ".css"),
            "Java":         ("text/x-java",             ".java"),
            "C":            ("text/x-csrc",             ".c"),
            "C++":          ("text/x-c++src",           ".cpp"),
            "Ruby":         ("text/x-ruby",             ".rb"),
            "PHP":          ("text/x-php",              ".php"),
            "Swift":        ("text/x-swift",            ".swift"),
            "Kotlin":       ("text/x-kotlin",           ".kt"),
            "Scala":        ("text/x-scala",            ".scala"),
            "R":            ("text/x-rsrc",             ".r"),
            "Lua":          ("text/x-lua",              ".lua"),
            "Perl":         ("text/x-perl",             ".pl"),
            "Haskell":      ("text/x-haskell",          ".hs"),
            "Elixir":       ("text/x-elixir",           ".ex"),
            "Erlang":       ("text/x-erlang",           ".erl"),
            "CSharp":       ("text/x-csharp",           ".cs"),
        }
        lexer_name = type(lexer).__name__.replace("Lexer", "")
        if lexer_name in EXT_MAP and lexer_name != "Text":
            return EXT_MAP[lexer_name]
    except (ImportError, Exception):
        pass

    return "text/plain", ".txt"


# ── Save (POST /save/) ────────────────────────────────────────────────────────

def drop_save(request):
    """Create or replace a drop. Accepts multipart (file) or form (text)."""
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    user        = request.user if request.user.is_authenticated else None

    # Require email verification for authenticated users before they can upload
    if user and not user.profile.email_verified:
        return JsonResponse({"error": "Please verify your email before uploading."}, status=403)
    anon_token  = _get_anon_token(request)
    custom_key  = (request.POST.get("key") or "").strip()
    expiry_days = request.POST.get("expiry_days")
    is_public   = request.POST.get("is_public") == "1"

    # ── Enforce max file size ──────────────────────────────────────────────
    if user:
        profile  = user.profile
        max_mb   = profile.plan_limits["max_file_mb"]
    else:
        profile  = None
        max_mb   = ANON_MAX_FILE_MB

    uploaded_file = request.FILES.get("file")
    text_content  = request.POST.get("content", "").strip()

    if not uploaded_file and not text_content:
        return JsonResponse({"error": "No content provided."}, status=400)

    if uploaded_file:
        if uploaded_file.size > max_mb * 1024 * 1024:
            return JsonResponse({"error": f"File too large. Max {max_mb} MB."}, status=413)
        if profile and not profile.has_storage_for(uploaded_file.size):
            return JsonResponse({"error": "Storage quota exceeded."}, status=413)

    # ── Validate custom key ────────────────────────────────────────────────
    if custom_key:
        import re
        if not re.match(r'^[a-zA-Z0-9_\-]{1,64}$', custom_key):
            return JsonResponse({"error": "Invalid key. Use letters, numbers, hyphens, underscores."}, status=400)
        # Check if taken by someone else
        existing = File.objects.filter(key=custom_key).first()
        if existing and not _can_edit(request, existing):
            return JsonResponse({"error": "Key already taken."}, status=409)

    # ── Upload to B2 ───────────────────────────────────────────────────────
    try:
        if uploaded_file:
            ct = uploaded_file.content_type or mimetypes.guess_type(uploaded_file.name)[0] or "application/octet-stream"
            b2_name, size = b2_upload(uploaded_file, uploaded_file.name, ct)
            filename      = uploaded_file.name
            content_type  = ct
        else:
            from core.models import generate_key as _gk
            tmp_key          = custom_key or _gk()
            content_type, ext = _sniff_content_type(text_content)
            filename         = f"{tmp_key}{ext}"
            b2_name, size    = b2_upload_text(text_content, tmp_key)
    except Exception as e:
        logger.exception("B2 upload error")
        return JsonResponse({"error": "Upload failed. Try again."}, status=500)

    # ── Create or update File record ───────────────────────────────────────
    expires_at = _expiry_for_user(request, expiry_days)

    # Check if this is a replace (key already exists and user owns it)
    drop = None
    if custom_key:
        drop = File.objects.filter(key=custom_key).first()
        if drop and _can_edit(request, drop):
            # Delete old B2 object
            try:
                b2_delete(drop.b2_name)
            except Exception:
                pass
            # Update storage tracking
            if profile:
                UserProfile.objects.filter(user=user).update(
                    storage_used_bytes=max(0, profile.storage_used_bytes - drop.size + size)
                )
            drop.b2_name      = b2_name
            drop.filename     = filename
            drop.content_type = content_type
            drop.size         = size
            drop.expires_at   = expires_at
            drop.updated_at   = timezone.now()
            drop.save()
        elif drop:
            return JsonResponse({"error": "Key already taken."}, status=409)

    if not drop:
        drop = File.objects.create(
            key          = custom_key or None,
            owner        = user,
            anon_token   = anon_token if not user else "",
            b2_name      = b2_name,
            filename     = filename,
            content_type = content_type,
            size         = size,
            expires_at   = expires_at,
            is_public    = is_public if user else False,
        )

    # Always assign authenticated uploads to a folder.
    # For the web UI we use a special root folder "__root__" per user.
    # Anon uploads are keyless and have no folder.
    if user:
        from django.utils.text import slugify as _slugify
        root_slug = "__root__"
        root_folder, _ = Folder.objects.get_or_create(
            owner=user, slug=root_slug, parent=None,
            defaults={"is_public": False},
        )
        FolderItem.objects.get_or_create(
            folder=root_folder, key=drop.key,
            defaults={"label": filename},
        )

    # Update storage used
    if profile:
        UserProfile.objects.filter(user=user).update(
            storage_used_bytes=profile.storage_used_bytes + size
        )

    return JsonResponse({"key": drop.key, "url": f"/{drop.key}/", "content_type": drop.content_type})


# ── View (GET /<key>/) ────────────────────────────────────────────────────────

def drop_view(request, key):
    drop = get_object_or_404(File, key=key)

    # Expired
    if drop.is_expired:
        try:
            b2_delete(drop.b2_name)
        except Exception:
            pass
        drop.delete()
        return render(request, "expired.html", {"key": key}, status=410)

    # Not yet visible (scheduled)
    if hasattr(drop, "visible_from") and drop.visible_from and drop.visible_from > timezone.now():
        if not (request.user.is_authenticated and drop.owner == request.user):
            raise Http404

    # Password gate
    if drop.is_password_protected and not _check_password(request, drop):
        if request.method == "POST":
            pw = request.POST.get("drop_password", "")
            if _hash_password(pw) == drop.password_hash:
                request.session[f"{PASSWORD_SESSION_PREFIX}{drop.key}"] = True
                return redirect("drop_view", key=key)
            return render(request, "password_prompt.html", {"drop": drop, "next": request.path, "error": "Wrong password."})
        return render(request, "password_prompt.html", {"drop": drop, "next": request.path})

    # Bump stats
    File.objects.filter(pk=drop.pk).update(
        view_count=drop.view_count + 1,
        last_viewed_at=timezone.now(),
    )

    # Burn after read
    if drop.burn_after_read:
        try:
            b2_delete(drop.b2_name)
        except Exception:
            pass
        drop.delete()
        return render(request, "expired.html", {"key": key})

    can_edit   = _can_edit(request, drop)
    is_owner   = request.user.is_authenticated and drop.owner == request.user
    is_paid_owner = is_owner and request.user.profile.is_paid

    # For text drops, inline-load content so the template can display it
    text_content = None
    if drop.content_type.startswith("text/"):
        try:
            text_content = b2_read(drop.b2_name).decode("utf-8", errors="replace")
        except Exception:
            text_content = ""

    # Liked by current user?
    user_liked = False
    if request.user.is_authenticated:
        user_liked = Like.objects.filter(file=drop, user=request.user).exists()

    ctx = {
        "drop":         drop,
        "can_edit":     can_edit,
        "is_owner":     is_owner,
        "is_paid_owner": is_paid_owner,
        "text_content": text_content,
        "user_liked":   user_liked,
    }

    # JSON API response for CLI
    if request.headers.get("Accept") == "application/json":
        data = {
            "key":          drop.key,
            "filename":     drop.filename,
            "content_type": drop.content_type,
            "size":         drop.size,
            "expires_at":   drop.expires_at.isoformat() if drop.expires_at else None,
        }
        if text_content is not None:
            data["content"] = text_content
        else:
            data["download_url"] = b2_download_url(drop.b2_name)
        return JsonResponse(data)

    return render(request, "drop.html", ctx)


# ── Raw text (GET /<key>/raw/) ────────────────────────────────────────────────

def drop_raw(request, key):
    drop = get_object_or_404(File, key=key)
    if drop.is_expired:
        raise Http404
    if drop.is_password_protected and not _check_password(request, drop):
        return redirect("drop_view", key=key)
    try:
        content = b2_read(drop.b2_name)
    except Exception:
        raise Http404
    return HttpResponse(content, content_type=drop.content_type or "text/plain")


# ── Download (GET /<key>/download/) ──────────────────────────────────────────

def drop_download(request, key):
    drop = get_object_or_404(File, key=key)
    if drop.is_expired:
        raise Http404
    if drop.is_password_protected and not _check_password(request, drop):
        return redirect("drop_view", key=key)
    url = b2_download_url(drop.b2_name, expires=300)
    return HttpResponseRedirect(url)


# ── Embed (GET /embed/<key>/) ────────────────────────────────────────────────

def drop_embed(request, key):
    drop = get_object_or_404(File, key=key)
    if drop.is_expired:
        raise Http404

    text_content = None
    if drop.content_type.startswith("text/"):
        try:
            text_content = b2_read(drop.b2_name).decode("utf-8", errors="replace")
        except Exception:
            text_content = ""

    # Override drop.content for the embed template (which still checks drop.kind)
    # We inject content_type-aware context instead
    ctx = {
        "drop":         drop,
        "text_content": text_content,
        "raw_url":      f"/{key}/raw/",
        "download_url": f"/{key}/download/",
    }
    return render(request, "embed.html", ctx)


# ── Delete (DELETE /<key>/delete/) ────────────────────────────────────────────

def drop_delete(request, key):
    if request.method not in ("DELETE", "POST"):
        return JsonResponse({"error": "Method not allowed"}, status=405)
    drop = get_object_or_404(File, key=key)
    if not _can_edit(request, drop):
        return JsonResponse({"error": "Not allowed."}, status=403)
    try:
        b2_delete(drop.b2_name)
    except Exception:
        pass
    # Update storage
    if drop.owner:
        try:
            profile = drop.owner.profile
            UserProfile.objects.filter(user=drop.owner).update(
                storage_used_bytes=max(0, profile.storage_used_bytes - drop.size)
            )
        except Exception:
            pass
    drop.delete()
    return JsonResponse({"ok": True})


# ── Rename / setkey (POST /<key>/rename/) ────────────────────────────────────

@require_POST
def drop_rename(request, key):
    drop = get_object_or_404(File, key=key)
    if not _can_edit(request, drop):
        return JsonResponse({"error": "Not allowed."}, status=403)

    new_key = (request.POST.get("new_key") or "").strip()
    import re
    if not new_key or not re.match(r'^[a-zA-Z0-9_\-]{1,64}$', new_key):
        return JsonResponse({"error": "Invalid key."}, status=400)
    if new_key == key:
        return JsonResponse({"url": f"/{key}/"})
    if File.objects.filter(key=new_key).exists():
        return JsonResponse({"error": "Key already taken."}, status=409)

    # Reset expiry on rename
    user = request.user if request.user.is_authenticated else None
    if user:
        limits     = user.profile.plan_limits
        new_expiry = timezone.now() + timedelta(days=limits["max_expiry_days"])
    else:
        new_expiry = timezone.now() + timedelta(days=ANON_LIFETIME_DAYS)

    drop.key        = new_key
    drop.expires_at = new_expiry
    drop.save(update_fields=["key", "expires_at", "updated_at"])
    return JsonResponse({"url": f"/{new_key}/"})


# ── Bookmark: save (POST /<key>/save/) ───────────────────────────────────────

@login_required
@require_POST
def drop_save_bookmark(request, key):
    get_object_or_404(File, key=key)   # ensure drop exists
    FileBookmark.objects.get_or_create(user=request.user, file_key=key)
    return JsonResponse({"ok": True})


# ── Bookmark: remove (POST /<key>/unsave/) ───────────────────────────────────

@login_required
@require_POST
def drop_remove_bookmark(request, key):
    FileBookmark.objects.filter(user=request.user, file_key=key).delete()
    return JsonResponse({"ok": True})


# ── Like (POST /<key>/like/) ─────────────────────────────────────────────────

@require_POST
def drop_like(request, key):
    drop = get_object_or_404(File, key=key)
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Login required."}, status=401)

    liked = Like.objects.filter(file=drop, user=request.user).exists()
    if liked:
        Like.objects.filter(file=drop, user=request.user).delete()
        liked = False
    else:
        Like.objects.get_or_create(file=drop, user=request.user)
        liked = True

    return JsonResponse({"liked": liked, "like_count": drop.like_count})


# ── Set password (POST /<key>/set-password/) ─────────────────────────────────

@login_required
@require_POST
def drop_set_password(request, key):
    drop = get_object_or_404(File, key=key)
    if not (request.user.is_authenticated and drop.owner == request.user and request.user.profile.is_paid):
        return JsonResponse({"error": "Not allowed."}, status=403)

    import json as _json
    try:
        body = _json.loads(request.body)
    except Exception:
        return JsonResponse({"error": "Bad JSON."}, status=400)

    pw = body.get("password", "").strip()
    if pw:
        drop.password_hash = _hash_password(pw)
        drop.save(update_fields=["password_hash"])
        return JsonResponse({"message": "Password set."})
    else:
        drop.password_hash = ""
        drop.save(update_fields=["password_hash"])
        return JsonResponse({"message": "Password removed."})


# ── Check key availability (GET /check-key/?key=...) ─────────────────────────

@require_GET
def check_key(request):
    key = request.GET.get("key", "").strip()
    import re
    if not key or not re.match(r'^[a-zA-Z0-9_\-]{1,64}$', key):
        return JsonResponse({"available": False, "error": "Invalid key format."})
    available = not File.objects.filter(key=key).exists()
    return JsonResponse({"available": available})
