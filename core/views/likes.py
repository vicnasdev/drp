"""
Like views: toggle like on public drops.

Only logged-in users can like. Liking is a toggle —
POST once to like, POST again to unlike.
"""

from django.http import JsonResponse
from django.views.decorators.http import require_POST

from core.models import Drop, Like
from core.views.helpers import client_ip


@require_POST
def toggle_like(request, key):
    """Anyone can like (logged-in or anon). Anon likes tracked by IP."""
    try:
        drop = Drop.objects.get(key=key, is_public=True)
    except Drop.DoesNotExist:
        return JsonResponse({"error": "Drop not found or not public."}, status=404)

    user = request.user if request.user.is_authenticated else None
    ip = client_ip(request)

    if user:
        like, created = Like.objects.get_or_create(drop=drop, user=user, defaults={"ip": ip})
    else:
        like, created = Like.objects.get_or_create(drop=drop, user=None, ip=ip)

    if not created:
        like.delete()

    count = Like.objects.filter(drop=drop).count()
    return JsonResponse({"liked": created, "like_count": count})
