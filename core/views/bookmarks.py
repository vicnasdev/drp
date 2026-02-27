"""
Bookmark views: save and unsave a drop.

Saving a drop adds it to the user's root folder ("My Drops").
This replaces the old SavedDrop model with FolderItem.
"""

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from core.models import Drop, Folder, FolderItem


def _root_folder(user):
    """Return the user's root folder, creating it if needed."""
    folder, _ = Folder.objects.get_or_create(
        owner=user, parent=None, slug="drops",
        defaults={"name": "My Drops"},
    )
    return folder


@login_required
@require_POST
def save_bookmark(request, key):
    if not Drop.objects.filter(key=key).exists():
        return JsonResponse({'error': 'Drop not found.'}, status=404)
    folder = _root_folder(request.user)
    _, created = FolderItem.objects.get_or_create(folder=folder, key=key)
    return JsonResponse({'saved': True, 'created': created})


@login_required
@require_POST
def unsave_bookmark(request, key):
    folder = _root_folder(request.user)
    deleted, _ = FolderItem.objects.filter(folder=folder, key=key).delete()
    return JsonResponse({'saved': False, 'deleted': bool(deleted)})