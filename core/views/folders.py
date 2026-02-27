"""
Folder views — unified organiser with nesting and group-based sharing.

URL patterns:
  GET  /@username/                           — list user's folders (public)
  GET  /@username/<path>/                    — view a folder (public)
  POST /folders/create/                      — create folder (owner, paid)
  POST /folders/<id>/add/                    — add drop to folder (owner / writer+)
  POST /folders/<id>/remove/                 — remove drop from folder (owner / writer+)
  POST /folders/<id>/delete/                 — delete folder (owner)
  POST /folders/<id>/rename/                 — rename folder (owner / admin)
  POST /folders/<id>/share/                  — create share token (owner / admin)
  GET  /folders/<id>/share/list/             — list share tokens
  POST /folders/<id>/share/<tid>/revoke/     — revoke share token

Auth / sharing rules:
  - Anyone can view a folder page and its public drop list.
  - Creating/editing folders requires login + paid plan.
  - Group members gain access via FolderGroup links.
  - Readers can view; writers can add/remove drops; admins can manage.
  - The owner always has full control.

Plan downgrade policy:
  Data is NEVER deleted. Over-quota folders become inaccessible to the owner
  until they upgrade or delete surplus. Public viewers always see read-only.
  DELETE is always allowed.
"""

import json
import re
import secrets

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from core.models import (
    Folder, FolderItem, FolderGroup, FolderShareToken,
    Drop, Plan,
)
from core.views.helpers import user_plan, can_user_access_folder


_SLUG_RE = re.compile(r'^[a-zA-Z0-9_-]{1,60}$')


def _folder_quota_ok(user):
    """Returns (ok: bool, limit: int|None)."""
    plan = user_plan(user)
    limit = Plan.get(plan, "max_folders")
    if limit is None:
        return True, None  # unlimited (Pro)
    current = Folder.objects.filter(owner=user).count()
    return current < limit, limit


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_folder_admin(user, folder):
    """True if user is the owner or has admin role via a group."""
    if folder.owner_id == user.pk:
        return True
    return FolderGroup.objects.filter(
        folder=folder,
        group__members__user=user,
        role=FolderGroup.ROLE_ADMIN,
    ).exists()


def _is_folder_member(user, folder, min_role=None):
    """True if user is the owner or a group member with at least the given role."""
    if folder.owner_id == user.pk:
        return True
    qs = FolderGroup.objects.filter(folder=folder, group__members__user=user)
    if min_role == FolderGroup.ROLE_WRITER:
        qs = qs.filter(role__in=[FolderGroup.ROLE_WRITER, FolderGroup.ROLE_ADMIN])
    elif min_role == FolderGroup.ROLE_ADMIN:
        qs = qs.filter(role=FolderGroup.ROLE_ADMIN)
    return qs.exists()


# ── Public views ──────────────────────────────────────────────────────────────

def user_folders(request, username):
    """GET /@username/ — list all folders for a user."""
    owner = get_object_or_404(User, username__iexact=username)
    folders = Folder.objects.filter(owner=owner).prefetch_related("items")
    return render(request, "folders/list.html", {
        "owner":   owner,
        "folders": folders,
        "is_own":  request.user.is_authenticated and request.user.pk == owner.pk,
    })


def folder_view(request, username, slug, folder=None):
    """GET /@username/<path>/ — view a folder."""
    owner = get_object_or_404(User, username__iexact=username)
    if folder is None:
        folder = get_object_or_404(Folder, owner=owner, slug=slug, parent=None)

    is_own = request.user.is_authenticated and request.user.pk == owner.pk

    # ── Access check for owner after plan downgrade ──
    if is_own:
        allowed, reason = can_user_access_folder(request.user, folder)
        if not allowed:
            if 'application/json' in request.headers.get('Accept', ''):
                return JsonResponse(
                    {"error": reason or "You no longer have access to this folder."},
                    status=403,
                )
            return render(request, "error.html", {
                "code": "Plan limit reached",
                "message": reason or "You no longer have access to this folder.",
            }, status=403)

    # ── GET ──
    items = folder.items.all()

    entries = []
    for item in items:
        drop = item.drop
        entries.append({"item": item, "drop": drop})

    if 'application/json' in request.headers.get('Accept', ''):
        from django.conf import settings as _settings
        site = getattr(_settings, 'SITE_URL', '')
        share_url = f"{site}/@{owner.username}/{folder.full_path}/"
        qr_url = f"{site}/qr/?url={share_url}"
        children = list(folder.children.all().values_list('slug', flat=True))
        return JsonResponse({
            'id':   folder.pk,
            'slug': folder.slug,
            'path': folder.full_path,
            'drops': [{'key': i.key} for i in items],
            'children': children,
            'share_url': share_url,
            'qr_url': qr_url,
        })

    # Owned drops available to add (for the add-drop UI)
    addable_drops = []
    if is_own:
        from django.db.models import OuterRef, Exists
        existing_items = FolderItem.objects.filter(
            folder=folder, key=OuterRef('key')
        )
        addable_drops = list(
            Drop.objects
            .filter(owner=request.user)
            .exclude(Exists(existing_items))
            .order_by("-created_at")[:100]
        )

    return render(request, "folders/detail.html", {
        "folder":       folder,
        "owner":        owner,
        "entries":      entries,
        "is_own":       is_own,
        "addable_drops": addable_drops,
    })


# ── Owner / member actions (JSON) ────────────────────────────────────────────

@login_required
@require_POST
def create_folder(request):
    """POST /folders/create/  body: {name, slug?, parent_id?}"""
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON."}, status=400)

    plan = user_plan(request.user)
    if Plan.get(plan, "max_folders") == 0:
        return JsonResponse(
            {"error": "Folders are a paid feature. Upgrade to Starter or Pro."},
            status=403,
        )

    ok, limit = _folder_quota_ok(request.user)
    if not ok:
        return JsonResponse(
            {"error": f"You've reached your folder limit ({limit}). Upgrade to Pro for unlimited."},
            status=403,
        )

    slug = (data.get("slug") or data.get("name") or "").strip()
    slug = slugify(slug)[:60]

    if not slug:
        return JsonResponse({"error": "Folder slug is required."}, status=400)

    if not _SLUG_RE.match(slug):
        return JsonResponse(
            {"error": "Slug may only contain letters, numbers, hyphens and underscores."},
            status=400,
        )

    parent = None
    parent_id = data.get("parent_id")
    if parent_id:
        parent = Folder.objects.filter(pk=parent_id, owner=request.user).first()
        if not parent:
            return JsonResponse({"error": "Parent folder not found."}, status=404)

    if Folder.objects.filter(owner=request.user, parent=parent, slug=slug).exists():
        return JsonResponse({"error": f'You already have a folder named "{slug}" at this level.'}, status=409)

    folder = Folder.objects.create(
        owner=request.user, slug=slug, parent=parent,
    )
    return JsonResponse({
        "id":   folder.pk,
        "slug": folder.slug,
        "path": folder.full_path,
        "url":  folder.url_path,
    }, status=201)


@login_required
@require_POST
def add_to_folder(request, folder_id):
    """POST /folders/<id>/add/  body: {key}"""
    folder = get_object_or_404(Folder, pk=folder_id)
    if not _is_folder_member(request.user, folder, min_role=FolderGroup.ROLE_WRITER):
        return JsonResponse({"error": "You don't have write access to this folder."}, status=403)

    allowed, reason = can_user_access_folder(request.user, folder)
    if not allowed and folder.owner_id == request.user.pk:
        return JsonResponse({"error": reason or "You no longer have access to this folder."}, status=403)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON."}, status=400)

    key = (data.get("key") or "").strip()

    if not key:
        return JsonResponse({"error": "key is required."}, status=400)
    if not Drop.objects.filter(key=key).exists():
        return JsonResponse({"error": "Drop not found."}, status=404)

    _, created = FolderItem.objects.get_or_create(folder=folder, key=key)
    return JsonResponse({"added": True, "created": created})


@login_required
@require_POST
def remove_from_folder(request, folder_id):
    """POST /folders/<id>/remove/  body: {key}"""
    folder = get_object_or_404(Folder, pk=folder_id)
    if not _is_folder_member(request.user, folder, min_role=FolderGroup.ROLE_WRITER):
        return JsonResponse({"error": "You don't have write access to this folder."}, status=403)

    allowed, reason = can_user_access_folder(request.user, folder)
    if not allowed and folder.owner_id == request.user.pk:
        return JsonResponse({"error": reason or "You no longer have access to this folder."}, status=403)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON."}, status=400)

    key = (data.get("key") or "").strip()

    deleted, _ = FolderItem.objects.filter(folder=folder, key=key).delete()
    return JsonResponse({"removed": bool(deleted)})


@login_required
@require_POST
def rename_folder(request, folder_id):
    """POST /folders/<id>/rename/  body: {slug}"""
    folder = get_object_or_404(Folder, pk=folder_id)
    if not _is_folder_admin(request.user, folder):
        return JsonResponse({"error": "Only the owner or admin can rename this folder."}, status=403)

    allowed, reason = can_user_access_folder(request.user, folder)
    if not allowed and folder.owner_id == request.user.pk:
        return JsonResponse({"error": reason or "You no longer have access to this folder."}, status=403)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON."}, status=400)

    new_slug = (data.get("slug") or "").strip()
    new_slug = slugify(new_slug)[:60]

    if not new_slug:
        return JsonResponse({"error": "Slug is required."}, status=400)

    if not _SLUG_RE.match(new_slug):
        return JsonResponse({"error": "Slug may only contain letters, numbers, hyphens and underscores."}, status=400)

    if new_slug != folder.slug:
        if Folder.objects.filter(owner=folder.owner, parent=folder.parent, slug=new_slug).exists():
            return JsonResponse({"error": f'A folder named "{new_slug}" already exists.'}, status=409)

    folder.slug = new_slug
    folder.save(update_fields=["slug"])

    return JsonResponse({
        "slug": folder.slug,
        "url":  folder.url_path,
    })


@login_required
@require_POST
def delete_folder(request, folder_id):
    """POST /folders/<id>/delete/ — always allowed (for cleanup)."""
    folder = get_object_or_404(Folder, pk=folder_id)
    if folder.owner_id != request.user.pk:
        return JsonResponse({"error": "Only the owner can delete this folder."}, status=403)
    folder.delete()
    return JsonResponse({"deleted": True})


# ── FolderShareToken management ──────────────────────────────────────────────

@login_required
@require_POST
def create_share_token(request, folder_id):
    """POST /folders/<id>/share/  body: {expires_hours?}"""
    folder = get_object_or_404(Folder, pk=folder_id)
    if not _is_folder_admin(request.user, folder):
        return JsonResponse({"error": "Only the owner or admin can share this folder."}, status=403)

    try:
        data = json.loads(request.body) if request.body else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        data = {}

    from django.utils import timezone as _tz
    from datetime import timedelta

    expires_hours = data.get("expires_hours", 24)
    try:
        expires_hours = float(expires_hours)
    except (ValueError, TypeError):
        expires_hours = 24

    expires_at = _tz.now() + timedelta(hours=expires_hours)

    token = secrets.token_urlsafe(32)
    share = FolderShareToken.objects.create(
        folder=folder,
        created_by=request.user,
        token=token,
        expires_at=expires_at,
    )

    from django.conf import settings as _settings
    site = getattr(_settings, 'SITE_URL', '')
    share_url = f"{site}/@{folder.owner.username}/{folder.full_path}/?t={token}"

    return JsonResponse({
        "token": token,
        "share_url": share_url,
        "expires_at": share.expires_at.isoformat() if share.expires_at else None,
    }, status=201)


@login_required
def list_share_tokens(request, folder_id):
    """GET /folders/<id>/share/list/"""
    folder = get_object_or_404(Folder, pk=folder_id)
    if not _is_folder_admin(request.user, folder):
        return JsonResponse({"error": "Only the owner or admin can view share tokens."}, status=403)

    tokens = FolderShareToken.objects.filter(folder=folder).order_by("-created_at")
    return JsonResponse({
        "tokens": [
            {
                "id": t.pk,
                "token": t.token,
                "expires_at": t.expires_at.isoformat() if t.expires_at else None,
                "expired": t.is_expired(),
                "created_at": t.created_at.isoformat(),
            }
            for t in tokens
        ],
    })


@login_required
@require_POST
def revoke_share_token(request, folder_id, token_id):
    """POST /folders/<id>/share/<tid>/revoke/"""
    folder = get_object_or_404(Folder, pk=folder_id)
    if not _is_folder_admin(request.user, folder):
        return JsonResponse({"error": "Only the owner or admin can revoke share tokens."}, status=403)

    deleted, _ = FolderShareToken.objects.filter(pk=token_id, folder=folder).delete()
    return JsonResponse({"revoked": bool(deleted)})


# ── Handle resolution ─────────────────────────────────────────────────────────

def resolve_handle(request, handle):
    """
    GET /@<handle>/ — resolve to a user's folder listing.
    """
    try:
        user = User.objects.get(username__iexact=handle)
    except User.DoesNotExist:
        from django.http import Http404
        raise Http404

    return user_folders(request, user.username)


def folder_or_item_view(request, username, path):
    """
    GET /@username/<path>/
    Resolve a folder path (supports nested sub-folders).
    If the last segment is a FolderItem label, render the drop.
    No alias fallback.
    """
    from django.http import Http404
    try:
        owner = User.objects.get(username__iexact=username)
    except User.DoesNotExist:
        raise Http404

    # Try full path as a folder first
    folder = Folder.resolve_path(owner, path)
    if folder:
        return folder_view(request, username, folder.slug, folder=folder)

    # Try folder + item (last segment is a file/drop label)
    folder, item = Folder.resolve_item(owner, path)
    if folder and item:
        drop = item.drop
        if not drop:
            raise Http404
        from core.views.drops import _drop_response
        return _drop_response(request, drop, folder_item=item)

    raise Http404