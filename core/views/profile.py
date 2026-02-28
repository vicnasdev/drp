"""
core/views/profile.py

Public profile and folder views: /@username/ and /@username/<folder>/
"""

from django.contrib.auth.models import User
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from core.models import File, Folder, FolderItem, FileBookmark


def profile_view(request, username):
    user     = get_object_or_404(User, username__iexact=username)
    is_owner = request.user.is_authenticated and request.user == user

    folders = Folder.objects.filter(owner=user, parent=None).exclude(slug="__root__")
    if not is_owner:
        folders = folders.filter(is_public=True)
    folders = folders.order_by("slug")

    # Public drops (files inside public folders) for non-owners
    # Owners see everything via the folder browser, not a flat list
    files = File.objects.none()
    if not is_owner:
        public_folder_keys = FolderItem.objects.filter(
            folder__owner=user, folder__is_public=True, folder__parent=None
        ).values_list("key", flat=True)
        files = (
            File.objects
            .filter(key__in=public_folder_keys, is_public=True)
            .exclude(expires_at__lt=timezone.now())
            .order_by("-created_at")[:50]
        )

    # Reuse folder.html — profile root IS just a folder view with no parent
    ctx = {
        "profile_user": user,
        "folder":       None,          # no parent folder — we're at root
        "files":        files,
        "subfolders":   folders,
        "is_owner":     is_owner,
        "is_root":      True,
    }
    return render(request, "folder.html", ctx)


def folder_view(request, username, folder_slug):
    user   = get_object_or_404(User, username__iexact=username)
    folder = get_object_or_404(Folder, owner=user, slug=folder_slug, parent=None)
    is_owner = request.user.is_authenticated and request.user == user

    # Access control
    if not folder.is_public and not is_owner:
        # Check share token
        token = request.GET.get("t")
        if token:
            from core.models import FolderShareToken
            try:
                st = folder.share_tokens.get(token=token)
                if not st.is_expired:
                    if request.user.is_authenticated:
                        FileBookmark.objects.get_or_create(
                            user=request.user, file_key=f"folder:{folder.pk}"
                        )
                    # Allow access
                else:
                    raise Http404
            except Exception:
                raise Http404
        else:
            raise Http404

    # Get files in this folder via FolderItem keys
    item_keys = FolderItem.objects.filter(folder=folder).values_list("key", flat=True)
    files = (
        File.objects
        .filter(key__in=item_keys)
        .exclude(expires_at__lt=timezone.now())
        .order_by("-created_at")
    )

    # Subfolders
    subfolders = Folder.objects.filter(owner=user, parent=folder).order_by("slug")

    ctx = {
        "profile_user": user,
        "folder":       folder,
        "files":        files,
        "subfolders":   subfolders,
        "is_owner":     is_owner,
    }
    return render(request, "folder.html", ctx)
