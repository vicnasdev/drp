from django.shortcuts import render
from django.utils import timezone

from core.models import File, FileBookmark, Folder, FolderItem


def home(request):
    ctx = {}

    if request.user.is_authenticated:
        # Show files the user owns, via their folder memberships.
        # No such thing as a loose drop — every file lives in a folder.
        filed_keys = (
            FolderItem.objects
            .filter(folder__owner=request.user)
            .values_list("key", flat=True)
        )
        server_drops = (
            File.objects
            .filter(owner=request.user, key__in=filed_keys)
            .exclude(expires_at__lt=timezone.now())
            .order_by("-created_at")[:20]
        )
        saved_keys = (
            FileBookmark.objects
            .filter(user=request.user)
            .order_by("-created_at")[:10]
        )
        folders = (
            Folder.objects
            .filter(owner=request.user, parent=None)
            .exclude(slug="__root__")   # hide the internal web-upload root folder
            .order_by("slug")
        )
        ctx.update({
            "server_drops": server_drops,
            "saved_drops":  saved_keys,
            "folders":      folders,
        })

    # Small public feed on homepage
    public_drops = (
        File.objects
        .filter(is_public=True)
        .exclude(expires_at__lt=timezone.now())
        .select_related("owner")
        .order_by("-created_at")[:12]
    )
    ctx["public_drops"] = public_drops

    return render(request, "home.html", ctx)
