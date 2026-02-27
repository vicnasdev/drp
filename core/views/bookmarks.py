"""
Bookmark views: save and unsave a drop.

Saving a drop adds it to the user's root folder ("My Drops").
This replaces the old SavedDrop model with FolderItem.
"""

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from core.models import Drop, Folder, FileBookmark, FolderBookmark


@login_required
@require_POST
def save_bookmark(request, key):
    """POST /bookmarks/<key>/save/ — bookmark a drop by key."""
    if not Drop.objects.filter(key=key).exists():
        return JsonResponse({'error': 'Drop not found.'}, status=404)
    _, created = FileBookmark.objects.get_or_create(user=request.user, file_key=key)
    return JsonResponse({'saved': True, 'created': created})


@login_required
@require_POST
def unsave_bookmark(request, key):
    """POST /bookmarks/<key>/unsave/ — remove a drop bookmark."""
    deleted, _ = FileBookmark.objects.filter(user=request.user, file_key=key).delete()
    return JsonResponse({'saved': False, 'deleted': bool(deleted)})


@login_required
@require_POST
def save_folder_bookmark(request, folder_id):
    """POST /bookmarks/folder/<id>/save/ — bookmark a folder."""
    from core.models import FolderShareToken
    import json

    folder = Folder.objects.filter(pk=folder_id).first()
    if not folder:
        return JsonResponse({'error': 'Folder not found.'}, status=404)

    share_token = None
    try:
        data = json.loads(request.body) if request.body else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        data = {}

    token_value = data.get('share_token')
    if token_value:
        share_token = FolderShareToken.objects.filter(
            folder=folder, token=token_value
        ).first()

    _, created = FolderBookmark.objects.get_or_create(
        user=request.user, folder=folder,
        defaults={'share_token': share_token},
    )
    return JsonResponse({'saved': True, 'created': created})


@login_required
@require_POST
def unsave_folder_bookmark(request, folder_id):
    """POST /bookmarks/folder/<id>/unsave/ — remove a folder bookmark."""
    deleted, _ = FolderBookmark.objects.filter(
        user=request.user, folder_id=folder_id
    ).delete()
    return JsonResponse({'saved': False, 'deleted': bool(deleted)})