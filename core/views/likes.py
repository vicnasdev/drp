"""
Like views: toggle like on public drops.

Only logged-in users can like. Liking is a toggle —
POST once to like, POST again to unlike.
"""

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from core.models import Drop, DropLike


@login_required
@require_POST
def toggle_like(request, key):
    try:
        drop = Drop.objects.get(key=key, is_public=True)
    except Drop.DoesNotExist:
        return JsonResponse({"error": "Drop not found or not public."}, status=404)

    like, created = DropLike.objects.get_or_create(drop=drop, user=request.user)
    if not created:
        like.delete()

    count = DropLike.objects.filter(drop=drop).count()
    return JsonResponse({"liked": created, "like_count": count})
