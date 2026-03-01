"""Drive views — file pages, profiles, explore, embeds."""

import hashlib
import json
import mimetypes

from django.conf import settings
from django.contrib.auth.models import User
from django.http import Http404, HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from drive.models import Bookmark, File, Folder, Key, Like


# ── home / contact ───────────────────────────────────────────────────────

def home_view(request):
    """GET  /  — landing page with upload form."""
    return render(request, "home.html")


def contact_view(request):
    """GET/POST  /contact/  — contact / bug-report form."""
    if request.method == "POST":
        category = request.POST.get("category", "")
        description = request.POST.get("description", "")
        if not category or not description:
            return render(request, "contact/bug_report.html", {"error": "All fields are required."})
        # In production this would file a GitHub issue or send an email.
        return render(request, "contact/bug_report_done.html")
    return render(request, "contact/bug_report.html")


def use_cases_view(request):
    """GET  /use-cases/  — static page."""
    return render(request, "pages/use_cases.html")


# ── helpers ──────────────────────────────────────────────────────────────

def _check_password(request, obj, session_prefix):
    """Return True if obj has no password or the user already unlocked it."""
    if not obj.is_password_protected:
        return True
    return request.session.get(f"{session_prefix}_{obj.pk}") is True


def _verify_password(stored_hash, raw):
    """Simple PBKDF2-SHA256 check (matches the hash we store)."""
    if not stored_hash:
        return False
    try:
        algo, iterations, salt, h = stored_hash.split("$", 3)
        dk = hashlib.pbkdf2_hmac(
            "sha256", raw.encode(), salt.encode(), int(iterations)
        )
        return dk.hex() == h
    except (ValueError, TypeError):
        return False


# ── key views ────────────────────────────────────────────────────────────

def key_view(request, key):
    """GET  /{key}/  — file page.  POST handles password unlock."""
    obj = get_object_or_404(Key, key=key)

    if obj.is_expired:
        return render(request, "drive/expired.html", {"key": key}, status=410)
    if obj.is_burned:
        return render(request, "drive/expired.html", {"key": key}, status=410)

    # Password gate
    if not _check_password(request, obj, "key_pw"):
        if request.method == "POST":
            raw = request.POST.get("drop_password", "")
            if _verify_password(obj.password_hash, raw):
                request.session[f"key_pw_{obj.pk}"] = True
            else:
                return render(request, "drive/password_prompt.html", {
                    "drop": obj, "next": request.path, "error": True,
                })
        else:
            return render(request, "drive/password_prompt.html", {
                "drop": obj, "next": request.path,
            })

    # Burn after first view
    obj.mark_burned()

    f = obj.file
    is_owner = request.user.is_authenticated and f.owner == request.user
    can_edit = is_owner and not getattr(obj, "locked", False)

    text_content = None
    if f.content_type.startswith("text/"):
        # Text content would be fetched from B2 via presigned URL in
        # production.  Placeholder for now.
        text_content = ""

    return render(request, "drive/drop.html", {
        "drop": obj,
        "file": f,
        "is_owner": is_owner,
        "can_edit": can_edit,
        "is_paid_owner": is_owner and hasattr(request.user, "profile")
            and request.user.profile.plan in ("starter", "pro"),
        "text_content": text_content,
    })


def key_raw(request, key):
    """GET  /{key}/raw/  — redirect to presigned B2 URL."""
    obj = get_object_or_404(Key, key=key)
    if not obj.is_valid:
        raise Http404
    if not _check_password(request, obj, "key_pw"):
        return redirect(f"/{key}/")
    # In production: generate presigned URL and redirect.
    return HttpResponse(
        "raw content served via presigned B2 URL",
        content_type=obj.file.content_type,
    )


def key_download(request, key):
    """GET  /{key}/download/  — force-download via presigned URL."""
    obj = get_object_or_404(Key, key=key)
    if not obj.is_valid:
        raise Http404
    if not _check_password(request, obj, "key_pw"):
        return redirect(f"/{key}/")
    response = HttpResponse(
        "download served via presigned B2 URL",
        content_type="application/octet-stream",
    )
    response["Content-Disposition"] = f'attachment; filename="{obj.file.filename}"'
    return response


@require_POST
def key_decrypt(request, key):
    """POST  /{key}/decrypt/  — permanently remove encryption (owner only).

    In production this would: fetch from B2, decrypt with the passphrase,
    re-upload without encryption, and flip file.encrypted = False.
    For now we just validate ownership, flip the flag, and return OK.
    """
    obj = get_object_or_404(Key, key=key)
    if not obj.is_valid:
        return JsonResponse({"error": "key is expired or burned"}, status=410)
    if not request.user.is_authenticated or obj.file.owner != request.user:
        return JsonResponse({"error": "only the owner can decrypt"}, status=403)
    if not obj.file.encrypted:
        return JsonResponse({"error": "file is not encrypted"}, status=400)
    try:
        body = json.loads(request.body)
        encryption_key = body.get("encryption_key", "")
    except (json.JSONDecodeError, AttributeError):
        encryption_key = ""
    if not encryption_key:
        return JsonResponse({"error": "encryption_key is required"}, status=400)
    # TODO: In production, download from B2, decrypt with encryption_key,
    #       re-upload plaintext, update b2_key.
    obj.file.encrypted = False
    obj.file.save(update_fields=["encrypted"])
    return JsonResponse({"ok": True})


# ── embed ────────────────────────────────────────────────────────────────

def embed(request, key):
    """GET  /embed/{key}/  — iframe-friendly view."""
    obj = get_object_or_404(Key, key=key)
    if not obj.is_valid:
        raise Http404
    text_content = "" if obj.file.content_type.startswith("text/") else None
    return render(request, "drive/embed.html", {
        "drop": obj,
        "text_content": text_content,
    })


# ── explore ──────────────────────────────────────────────────────────────

def explore(request):
    """GET  /explore/  — published files feed."""
    qs = Key.objects.filter(publish=True).select_related("file", "file__owner")

    q = request.GET.get("q", "").strip()
    tag = request.GET.get("tag", "").strip()
    sort = request.GET.get("sort", "").strip()

    if q:
        qs = qs.filter(file__filename__icontains=q)
    if tag:
        qs = qs.filter(tags__contains=[tag])
    if sort == "likes":
        qs = qs.order_by("-like_count", "-created_at")
    else:
        qs = qs.order_by("-created_at")

    # Filter out expired / burned
    qs = [k for k in qs[:200] if k.is_valid]

    user_liked_ids = set()
    if request.user.is_authenticated:
        user_liked_ids = set(
            Like.objects.filter(user=request.user, key__in=[k.pk for k in qs])
            .values_list("key_id", flat=True)
        )

    return render(request, "drive/explore.html", {
        "drops": qs,
        "user_liked_ids": user_liked_ids,
        "q": q,
        "tag": tag,
        "sort": sort,
    })


# ── profile / path ──────────────────────────────────────────────────────

def profile(request, username):
    """GET  /@{username}/  — user profile / root folder listing."""
    user = get_object_or_404(User, username=username)
    is_owner = request.user == user

    if is_owner:
        folders = Folder.objects.filter(owner=user, parent=None)
        files = File.objects.filter(owner=user, folder=None)
    else:
        # Visitors see only published keys and path-public folders
        folders = Folder.objects.filter(owner=user, parent=None, path_public=True)
        files = File.objects.none()

    return render(request, "auth/folder.html", {
        "profile_user": user,
        "is_owner": is_owner,
        "folder": None,
        "subfolders": folders,
        "files": files,
    })


def path_view(request, username, path):
    """GET  /@{username}/{path}/  — resolve folder or file by path."""
    user = get_object_or_404(User, username=username)
    is_owner = request.user == user
    parts = [p for p in path.strip("/").split("/") if p]

    if not parts:
        return redirect("profile", username=username)

    # Walk the folder tree
    parent = None
    for i, slug in enumerate(parts[:-1]):
        folder = Folder.objects.filter(
            owner=user, parent=parent, slug=slug
        ).first()
        if folder is None:
            raise Http404
        parent = folder

    # Last segment: could be a folder or a file
    last = parts[-1]

    folder = Folder.objects.filter(
        owner=user, parent=parent, slug=last
    ).first()
    if folder:
        # Non-owner path access check
        if not is_owner and not folder.path_access_allowed():
            return HttpResponseForbidden("path access is not enabled for this folder")

        # Closest-ancestor password gate
        gate = folder.nearest_password_ancestor()
        if gate and not _check_password(request, gate, "folder_pw"):
            if request.method == "POST":
                raw = request.POST.get("drop_password", "")
                if _verify_password(gate.password_hash, raw):
                    request.session[f"folder_pw_{gate.pk}"] = True
                else:
                    return render(request, "drive/password_prompt.html", {
                        "drop": gate, "next": request.path, "error": True,
                    })
            else:
                return render(request, "drive/password_prompt.html", {
                    "drop": gate, "next": request.path,
                })

        subfolders = folder.children.all()
        files = folder.files.all()
        if not is_owner:
            subfolders = subfolders.filter(path_public=True)

        return render(request, "auth/folder.html", {
            "profile_user": user,
            "is_owner": is_owner,
            "folder": folder,
            "subfolders": subfolders,
            "files": files,
        })

    # Try file
    file = File.objects.filter(
        owner=user, folder=parent, filename=last
    ).first()
    if file is None:
        raise Http404

    # Check path access on the containing folder
    if not is_owner and parent and not parent.path_access_allowed():
        return HttpResponseForbidden("path access is not enabled for this folder")

    # Closest-ancestor password gate for file access
    if parent:
        gate = parent.nearest_password_ancestor()
        if gate and not _check_password(request, gate, "folder_pw"):
            if request.method == "POST":
                raw = request.POST.get("drop_password", "")
                if _verify_password(gate.password_hash, raw):
                    request.session[f"folder_pw_{gate.pk}"] = True
                else:
                    return render(request, "drive/password_prompt.html", {
                        "drop": gate, "next": request.path, "error": True,
                    })
            else:
                return render(request, "drive/password_prompt.html", {
                    "drop": gate, "next": request.path,
                })

    # Redirect to the file's primary key URL
    key = file.keys.filter(burned=False).first()
    if key is None:
        raise Http404
    return redirect("key_view", key=key.key)
