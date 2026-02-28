"""
core/views/folder.py

Folder CRUD: create, add items, remove items.
"""

import json

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from core.models import Folder, FolderItem, UserProfile, PLAN_LIMITS


@login_required
@require_POST
def folder_add(request, folder_id):
    """Add a drop (by key) to a folder."""
    folder = get_object_or_404(Folder, pk=folder_id, owner=request.user)

    try:
        body = json.loads(request.body)
    except Exception:
        return JsonResponse({"error": "Bad JSON."}, status=400)

    key = (body.get("key") or "").strip()
    if not key:
        return JsonResponse({"error": "No key provided."}, status=400)

    _, created = FolderItem.objects.get_or_create(folder=folder, key=key)
    return JsonResponse({"ok": True, "created": created})


@login_required
@require_POST
def folder_create(request):
    """Create a new folder. POST body: {slug: str, parent_id?: int}"""
    try:
        body = json.loads(request.body)
    except Exception:
        body = {}

    raw_slug  = (body.get("slug") or request.POST.get("slug") or "").strip()
    parent_id = body.get("parent_id") or request.POST.get("parent_id")
    slug      = slugify(raw_slug)[:128]

    if not slug:
        return JsonResponse({"error": "Invalid folder name."}, status=400)

    # Check quota
    profile     = request.user.profile
    limits      = PLAN_LIMITS.get(profile.plan, PLAN_LIMITS["free"])
    max_folders = limits.get("max_folders")
    if max_folders is not None:
        count = Folder.objects.filter(owner=request.user).count()
        if count >= max_folders:
            return JsonResponse(
                {"error": f"Folder limit reached ({max_folders}). Upgrade for more."},
                status=403,
            )

    parent = None
    if parent_id:
        parent = get_object_or_404(Folder, pk=parent_id, owner=request.user)

    if Folder.objects.filter(owner=request.user, parent=parent, slug=slug).exists():
        return JsonResponse({"error": "A folder with that name already exists."}, status=409)

    folder = Folder.objects.create(owner=request.user, slug=slug, parent=parent)
    return JsonResponse({"ok": True, "id": folder.pk, "slug": folder.slug})


@login_required
@require_POST
def folder_remove_item(request, folder_id, key):
    folder = get_object_or_404(Folder, pk=folder_id, owner=request.user)
    FolderItem.objects.filter(folder=folder, key=key).delete()
    return JsonResponse({"ok": True})


@login_required
@require_POST
def folder_delete(request, folder_id):
    folder = get_object_or_404(Folder, pk=folder_id, owner=request.user)
    folder.delete()
    return JsonResponse({"ok": True})
