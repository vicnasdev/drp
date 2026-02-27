"""
Folder views — unified organiser with nesting and sharing.

URL patterns:
  GET  /@username/                           — list user's folders (public)
  GET  /@username/<path>/                    — view a folder (public)
  POST /@username/<path>/                    — inbox: drop into public_inbox folder (anyone)
  POST /folders/create/                      — create folder (owner, paid)
  POST /folders/<id>/add/                    — add drop to folder (owner / writer+)
  POST /folders/<id>/remove/                 — remove drop from folder (owner / writer+)
  POST /folders/<id>/delete/                 — delete folder (owner)
  POST /folders/<id>/rename/                 — rename folder (owner / admin)
  POST /folders/<id>/toggle-inbox/           — toggle public_inbox (owner / admin)
  POST /folders/<id>/invite/                 — create invite token (owner / admin)
  POST /folders/join/                        — join folder via invite token
  POST /folders/<id>/members/<uid>/role/     — change member role (owner / admin)
  POST /folders/<id>/members/<uid>/remove/   — remove member (owner / admin)

Auth / sharing rules:
  - Anyone can view a folder page and its public drop list.
  - Creating/editing folders requires login + paid plan.
  - Members (reader/writer/admin) gain access through invite tokens.
  - Readers can view; writers can add/remove drops; admins can manage members.
  - The owner always has full control.

Plan downgrade policy:
  Data is NEVER deleted. Over-quota folders become inaccessible to the owner
  until they upgrade or delete surplus. Public viewers always see read-only.
  DELETE is always allowed.
"""

import json
import re
import secrets
import uuid

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from core.models import Folder, FolderItem, FolderMember, FolderInviteToken, Drop, Plan
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
    """True if user is the owner or has admin role."""
    if folder.owner_id == user.pk:
        return True
    return folder.members.filter(user=user, role=FolderMember.ROLE_ADMIN).exists()


def _is_folder_member(user, folder, min_role=None):
    """True if user is the owner or a member with at least the given role."""
    if folder.owner_id == user.pk:
        return True
    qs = folder.members.filter(user=user)
    if min_role == FolderMember.ROLE_WRITER:
        qs = qs.filter(role__in=[FolderMember.ROLE_WRITER, FolderMember.ROLE_ADMIN])
    elif min_role == FolderMember.ROLE_ADMIN:
        qs = qs.filter(role=FolderMember.ROLE_ADMIN)
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
    """GET/POST /@username/<path>/ — view a folder or drop into its inbox."""
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

    # ── Inbox POST (anyone can drop into public_inbox folders) ──
    if request.method == "POST":
        if not folder.public_inbox:
            return JsonResponse({"error": "This folder does not accept submissions."}, status=403)

        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JsonResponse({"error": "Invalid JSON."}, status=400)

        content = (data.get("content") or "").strip()
        if not content:
            return JsonResponse({"error": "Content is required."}, status=400)
        if len(content) > 50_000:
            return JsonResponse({"error": "Inbox drops limited to 50KB."}, status=400)

        key = uuid.uuid4().hex[:8]
        drop = Drop.objects.create(
            key=key,
            content=content,
            kind="text",
            owner=owner,
        )
        FolderItem.objects.create(folder=folder, key=key)
        return JsonResponse({"key": key, "url": f"/{key}/"}, status=201)

    # ── GET ──
    items = folder.items.all()

    entries = []
    for item in items:
        drop = item.drop
        entries.append({"item": item, "drop": drop})

    # Member list (for owner/admin)
    members = []
    if is_own or _is_folder_admin(request.user, folder) if request.user.is_authenticated else False:
        members = list(folder.members.select_related("user").all())

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
            'name': folder.name,
            'drops': [{'key': i.key} for i in items],
            'children': children,
            'share_url': share_url,
            'qr_url': qr_url,
            'members': [
                {'username': m.user.username, 'role': m.role}
                for m in members
            ],
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
        "members":      members,
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

    name = (data.get("name") or "").strip()
    if not name:
        return JsonResponse({"error": "Folder name is required."}, status=400)
    if len(name) > 120:
        return JsonResponse({"error": "Name must be 120 characters or fewer."}, status=400)

    slug = (data.get("slug") or "").strip() or slugify(name)
    slug = slug[:60]

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
        owner=request.user, slug=slug, name=name, parent=parent,
    )
    return JsonResponse({
        "id":   folder.pk,
        "slug": folder.slug,
        "path": folder.full_path,
        "name": folder.name,
        "url":  folder.url_path,
    }, status=201)


@login_required
@require_POST
def add_to_folder(request, folder_id):
    """POST /folders/<id>/add/  body: {key}"""
    folder = get_object_or_404(Folder, pk=folder_id)
    if not _is_folder_member(request.user, folder, min_role=FolderMember.ROLE_WRITER):
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
    if not _is_folder_member(request.user, folder, min_role=FolderMember.ROLE_WRITER):
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
    """POST /folders/<id>/rename/  body: {name, slug?}"""
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

    name = (data.get("name") or "").strip()
    if not name:
        return JsonResponse({"error": "Name is required."}, status=400)
    if len(name) > 120:
        return JsonResponse({"error": "Name must be 120 characters or fewer."}, status=400)

    new_slug = (data.get("slug") or "").strip() or slugify(name)
    new_slug = new_slug[:60]

    if not _SLUG_RE.match(new_slug):
        return JsonResponse({"error": "Slug may only contain letters, numbers, hyphens and underscores."}, status=400)

    if new_slug != folder.slug:
        if Folder.objects.filter(owner=folder.owner, slug=new_slug).exists():
            return JsonResponse({"error": f'A folder named "{new_slug}" already exists.'}, status=409)

    folder.name = name
    folder.slug = new_slug
    folder.save(update_fields=["name", "slug"])

    return JsonResponse({
        "name": folder.name,
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


@login_required
@require_POST
def toggle_inbox(request, folder_id):
    """POST /folders/<id>/toggle-inbox/"""
    folder = get_object_or_404(Folder, pk=folder_id)
    if not _is_folder_admin(request.user, folder):
        return JsonResponse({"error": "Only the owner or admin can change inbox settings."}, status=403)

    allowed, reason = can_user_access_folder(request.user, folder)
    if not allowed and folder.owner_id == request.user.pk:
        return JsonResponse({"error": reason or "You no longer have access to this folder."}, status=403)

    folder.public_inbox = not folder.public_inbox
    folder.save(update_fields=["public_inbox"])
    return JsonResponse({
        "public_inbox": folder.public_inbox,
        "message": "Inbox enabled." if folder.public_inbox else "Inbox disabled.",
    })


# ── Sharing / invite ─────────────────────────────────────────────────────────

@login_required
@require_POST
def create_invite(request, folder_id):
    """POST /folders/<id>/invite/  body: {role?, max_uses?, expires_hours?}"""
    folder = get_object_or_404(Folder, pk=folder_id)
    if not _is_folder_admin(request.user, folder):
        return JsonResponse({"error": "Only the owner or admin can create invites."}, status=403)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        data = {}

    role = data.get("role", FolderMember.ROLE_READER)
    if role not in dict(FolderMember.ROLE_CHOICES):
        return JsonResponse({"error": f"Invalid role: {role}"}, status=400)

    max_uses = data.get("max_uses")
    if max_uses is not None:
        try:
            max_uses = int(max_uses)
        except (ValueError, TypeError):
            return JsonResponse({"error": "max_uses must be an integer."}, status=400)

    from django.utils import timezone as _tz
    expires_at = None
    expires_hours = data.get("expires_hours")
    if expires_hours:
        try:
            expires_at = _tz.now() + __import__('datetime').timedelta(hours=float(expires_hours))
        except (ValueError, TypeError):
            return JsonResponse({"error": "expires_hours must be a number."}, status=400)

    token = secrets.token_urlsafe(32)
    invite = FolderInviteToken.objects.create(
        folder=folder,
        token=token,
        role=role,
        created_by=request.user,
        max_uses=max_uses,
        expires_at=expires_at,
    )
    return JsonResponse({
        "token": token,
        "role": role,
        "max_uses": max_uses,
        "expires_at": invite.expires_at.isoformat() if invite.expires_at else None,
    }, status=201)


@login_required
@require_POST
def join_folder(request):
    """POST /folders/join/  body: {token}"""
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON."}, status=400)

    token_value = (data.get("token") or "").strip()
    if not token_value:
        return JsonResponse({"error": "Token is required."}, status=400)

    invite = FolderInviteToken.objects.filter(token=token_value).first()
    if not invite:
        return JsonResponse({"error": "Invalid invite token."}, status=404)
    if invite.is_expired():
        return JsonResponse({"error": "This invite has expired."}, status=410)

    folder = invite.folder
    if folder.owner_id == request.user.pk:
        return JsonResponse({"error": "You already own this folder."}, status=400)

    member, created = FolderMember.objects.get_or_create(
        folder=folder, user=request.user,
        defaults={"role": invite.role},
    )

    if created:
        invite.use_count += 1
        invite.save(update_fields=["use_count"])

    from django.conf import settings as _settings
    site = getattr(_settings, 'SITE_URL', '')
    return JsonResponse({
        "joined": created,
        "role": member.role,
        "folder": folder.full_path,
        "url": f"{site}{folder.url_path}",
    })


@login_required
@require_POST
def change_member_role(request, folder_id, user_id):
    """POST /folders/<id>/members/<uid>/role/  body: {role}"""
    folder = get_object_or_404(Folder, pk=folder_id)
    if not _is_folder_admin(request.user, folder):
        return JsonResponse({"error": "Only the owner or admin can change roles."}, status=403)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON."}, status=400)

    role = data.get("role", "").strip()
    if role not in dict(FolderMember.ROLE_CHOICES):
        return JsonResponse({"error": f"Invalid role: {role}"}, status=400)

    membership = FolderMember.objects.filter(folder=folder, user_id=user_id).first()
    if not membership:
        return JsonResponse({"error": "User is not a member of this folder."}, status=404)

    membership.role = role
    membership.save(update_fields=["role"])
    return JsonResponse({"role": role, "user_id": user_id})


@login_required
@require_POST
def remove_member(request, folder_id, user_id):
    """POST /folders/<id>/members/<uid>/remove/"""
    folder = get_object_or_404(Folder, pk=folder_id)
    if not _is_folder_admin(request.user, folder):
        return JsonResponse({"error": "Only the owner or admin can remove members."}, status=403)

    deleted, _ = FolderMember.objects.filter(folder=folder, user_id=user_id).delete()
    return JsonResponse({"removed": bool(deleted)})


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


def folder_or_alias_view(request, username, path):
    """
    GET /@username/<path>/
    Resolve a folder path (supports nested sub-folders).
    If the last segment is a FolderItem label, render the drop.
    Falls back to alias resolution for single-segment paths.
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

    # Single-segment path → try alias resolution
    segments = [s for s in path.strip('/').split('/') if s]
    if len(segments) == 1:
        from core.views.aliases import resolve_alias
        return resolve_alias(request, username, segments[0])

    raise Http404
