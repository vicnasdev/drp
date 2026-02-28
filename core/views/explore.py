from django.shortcuts import render
from django.utils import timezone
from django.db.models import Q

from core.models import File, Like


def explore_view(request):
    q    = request.GET.get("q", "").strip()
    tag  = request.GET.get("tag", "").strip()
    sort = request.GET.get("sort", "")

    drops = (
        File.objects
        .filter(is_public=True)
        .exclude(expires_at__lt=timezone.now())
        .select_related("owner")
    )

    if q:
        drops = drops.filter(
            Q(filename__icontains=q) | Q(tags__icontains=q)
        )
    if tag:
        drops = drops.filter(tags__icontains=tag)

    if sort == "likes":
        # annotate with like count for ordering
        from django.db.models import Count
        drops = drops.annotate(like_count_ann=Count("likes")).order_by("-like_count_ann", "-created_at")
    else:
        drops = drops.order_by("-created_at")

    drops = drops[:50]

    # Which drops the current user has liked
    user_liked_ids = set()
    if request.user.is_authenticated:
        user_liked_ids = set(
            Like.objects.filter(user=request.user, file__in=drops).values_list("file_id", flat=True)
        )

    ctx = {
        "drops":          drops,
        "q":              q,
        "tag":            tag,
        "sort":           sort,
        "user_liked_ids": user_liked_ids,
    }
    return render(request, "explore.html", ctx)
