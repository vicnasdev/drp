"""
Drop action views: rename, delete, renew, copy.

URL patterns:
  Clipboard:  /key/rename/   /key/delete/   /key/renew/   /key/copy/
  File:       /f/key/rename/ /f/key/delete/ /f/key/renew/ /f/key/copy/
"""

import logging
import secrets

from django.http import JsonResponse
from django.utils import timezone

from core.models import Drop

logger = logging.getLogger(__name__)


def _get_drop(ns, key):
    return Drop.objects.filter(ns=ns, key=key).first()


def _edit_error(drop, request):
    if drop.is_expired():
        drop.hard_delete()
        return JsonResponse({'error': 'Drop has expired.'}, status=410)
    if not drop.can_edit(request.user):
        if drop.is_creation_locked():
            return JsonResponse(
                {'error': 'Drop is protected for 24 hours after creation.'},
                status=403,
            )
        return JsonResponse({'error': 'Drop is locked to its owner.'}, status=403)
    return None


# ── Rename ────────────────────────────────────────────────────────────────────

def rename_drop(request, ns, key):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required.'}, status=405)

    drop = _get_drop(ns, key)
    if not drop:
        return JsonResponse({'error': 'Drop not found.'}, status=404)

    err = _edit_error(drop, request)
    if err:
        return err

    new_key = request.POST.get('new_key', '').strip()
    if not new_key:
        return JsonResponse({'error': 'New key required.'}, status=400)
    if new_key == key:
        return JsonResponse({'error': 'New key is the same as current key.'}, status=400)
    if Drop.objects.filter(ns=ns, key=new_key).exists():
        return JsonResponse({'error': 'Key already taken.'}, status=409)

    # For file drops, preserve the B2 object key so downloads still work
    if drop.kind == Drop.FILE:
        from core.views.b2 import invalidate_presigned
        invalidate_presigned(ns, key, filename=drop.filename or "")
        if not drop.file_public_id:
            drop.file_public_id = drop.b2_object_key()

    drop.key = new_key
    fields = ['key']
    if drop.kind == Drop.FILE:
        fields.append('file_public_id')
    drop.save(update_fields=fields)

    prefix = '' if ns == Drop.NS_CLIPBOARD else 'f/'
    return JsonResponse({'key': new_key, 'url': f'/{prefix}{new_key}/'})


# ── Delete ────────────────────────────────────────────────────────────────────

def delete_drop(request, ns, key):
    if request.method != 'DELETE':
        return JsonResponse({'error': 'DELETE required.'}, status=405)

    drop = _get_drop(ns, key)
    if not drop:
        return JsonResponse({'error': 'Drop not found.'}, status=404)

    err = _edit_error(drop, request)
    if err:
        return err

    # Bust presigned cache before deleting
    if drop.kind == Drop.FILE:
        from core.views.b2 import invalidate_presigned
        invalidate_presigned(ns, key, filename=drop.filename or "")

    ok = drop.hard_delete()
    if not ok:
        logger.error("delete_drop: hard_delete failed for %s/%s", ns, key)
        return JsonResponse(
            {'error': 'File could not be removed from storage. Please try again.'},
            status=500,
        )
    return JsonResponse({'deleted': True})


# ── Renew ─────────────────────────────────────────────────────────────────────

def renew_drop(request, ns, key):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required.'}, status=405)

    drop = _get_drop(ns, key)
    if not drop:
        return JsonResponse({'error': 'Drop not found.'}, status=404)

    if drop.is_expired():
        drop.hard_delete()
        return JsonResponse({'error': 'Drop has expired.'}, status=410)

    if not (request.user.is_authenticated and drop.owner_id == request.user.pk):
        return JsonResponse({'error': 'Only the owner can renew this drop.'}, status=403)

    if not drop.expires_at:
        return JsonResponse(
            {'error': 'This drop has no explicit expiry date. Only paid drops can be renewed.'},
            status=400,
        )

    from core.models import Plan
    from core.views.helpers import user_plan
    allowed = Plan.get(user_plan(request.user), 'renewals')
    if allowed is not None and allowed <= 0:
        return JsonResponse(
            {'error': 'Your plan does not include renewals.'},
            status=403,
        )

    drop.renew()
    return JsonResponse({
        'expires_at': drop.expires_at.isoformat(),
        'renewals': drop.renewal_count,
    })


# ── Copy ──────────────────────────────────────────────────────────────────────

def copy_drop(request, ns, key):
    """
    POST /key/copy/ or /f/key/copy/

    Duplicates a drop under a new key. For text drops this is instant.
    For file drops we copy the B2 object server-side (no re-upload needed).

    Body (JSON, optional):
      { "new_key": "my-key" }   — use a specific key
      {}                         — generate a random key

    Returns:
      { "key": "new-key", "url": "/new-key/" }
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required.'}, status=405)

    drop = _get_drop(ns, key)
    if not drop:
        return JsonResponse({'error': 'Drop not found.'}, status=404)

    if drop.is_expired():
        drop.hard_delete()
        return JsonResponse({'error': 'Drop has expired.'}, status=410)

    import json
    try:
        data = json.loads(request.body) if request.body else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        data = {}

    new_key = (data.get('new_key') or '').strip() or secrets.token_urlsafe(6)

    if Drop.objects.filter(ns=ns, key=new_key).exists():
        return JsonResponse({'error': f'Key "{new_key}" is already taken.'}, status=409)

    owner = request.user if request.user.is_authenticated else None

    if drop.kind == Drop.TEXT:
        new_drop = Drop.objects.create(
            ns=ns,
            key=new_key,
            kind=Drop.TEXT,
            content=drop.content,
            owner=owner,
            locked=owner is not None,
            expires_at=drop.expires_at,
            max_lifetime_secs=drop.max_lifetime_secs,
        )
    else:
        # File drop — copy B2 object server-side
        from core.views.b2 import copy_object, object_key as b2_object_key
        src_b2_key = drop.b2_object_key()
        dst_b2_key = b2_object_key(ns, new_key)

        ok = copy_object(src_b2_key, dst_b2_key)
        if not ok:
            return JsonResponse({'error': 'Could not copy file in storage.'}, status=500)

        from core.views.helpers import add_storage
        new_drop = Drop.objects.create(
            ns=ns,
            key=new_key,
            kind=Drop.FILE,
            file_public_id=dst_b2_key,
            file_url='',
            filename=drop.filename,
            filesize=drop.filesize,
            owner=owner,
            locked=owner is not None,
            expires_at=drop.expires_at,
            max_lifetime_secs=drop.max_lifetime_secs,
        )
        add_storage(request.user, drop.filesize)

    prefix = 'f/' if ns == Drop.NS_FILE else ''
    return JsonResponse({'key': new_drop.key, 'url': f'/{prefix}{new_drop.key}/'})