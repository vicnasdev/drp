from django.shortcuts import render
from django.utils import timezone

from core.models import File, FileBookmark, Folder


def home(request):
    ctx = {}

    if request.user.is_authenticated:
        server_drops = (
            File.objects
            .filter(owner=request.user)
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
