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


# ── Switch (text ↔ file) ─────────────────────────────────────────────────────

def switch_drop(request, ns, key):
    """Convert a text drop to a file drop or vice-versa."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required.'}, status=405)

    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Login required.'}, status=401)

    drop = _get_drop(ns, key)
    if not drop:
        return JsonResponse({'error': 'Drop not found.'}, status=404)

    err = _edit_error(drop, request)
    if err:
        return err

    if drop.kind == Drop.TEXT:
        return _switch_text_to_file(request, drop)
    elif drop.kind == Drop.FILE:
        return _switch_file_to_text(request, drop)
    else:
        return JsonResponse({'error': 'Unknown drop kind.'}, status=400)


def _switch_text_to_file(request, drop):
    """Convert clipboard text → file drop.  Content-sniff for extension."""
    import io

    content = drop.content
    if not content:
        return JsonResponse({'error': 'Drop has no text content.'}, status=400)

    # Determine filename from POST or by sniffing content format
    filename = request.POST.get('filename', '').strip()
    if not filename:
        from cli.smart_parse import detect_format
        fmt = detect_format(content)
        ext_map = {'json': '.json', 'csv': '.csv', 'yaml': '.yml',
                    'xml': '.xml', 'text': '.txt'}
        filename = f'{drop.key}{ext_map.get(fmt, ".txt")}'

    content_bytes = content.encode('utf-8')
    content_type = 'text/plain; charset=utf-8'

    from core.views.helpers import max_file_bytes, storage_ok
    if len(content_bytes) > max_file_bytes(request.user):
        return JsonResponse({'error': 'Content exceeds file size limit.'}, status=400)
    if not storage_ok(request.user, len(content_bytes)):
        return JsonResponse({'error': 'Storage quota exceeded.'}, status=400)

    from core.views.b2 import upload_fileobj
    file_obj = io.BytesIO(content_bytes)
    new_ns = Drop.NS_FILE
    target_key = drop.key
    if Drop.objects.filter(ns=new_ns, key=target_key).exists():
        target_key = secrets.token_urlsafe(6)

    try:
        b2_key = upload_fileobj(file_obj, new_ns, target_key, content_type)
    except Exception as e:
        logger.error("switch text→file upload failed for %s: %s", drop.key, e)
        return JsonResponse({'error': f'Upload failed: {e}'}, status=500)

    old_expires = drop.expires_at
    old_max_lt = drop.max_lifetime_secs
    drop.delete()

    new_drop = Drop.objects.create(
        ns=new_ns, key=target_key, kind=Drop.FILE,
        file_public_id=b2_key, file_url='', filename=filename,
        filesize=len(content_bytes), content_type=content_type,
        owner=request.user, locked=True,
        expires_at=old_expires, max_lifetime_secs=old_max_lt,
    )

    from core.views.helpers import add_storage
    add_storage(request.user, len(content_bytes))

    return JsonResponse({
        'key': new_drop.key, 'ns': new_drop.ns, 'kind': new_drop.kind,
        'url': f'/f/{new_drop.key}/', 'filename': filename,
    })


def _switch_file_to_text(request, drop):
    """Convert file drop → clipboard text.  Only works for textual files."""
    from core.views.b2 import _b2, object_key as b2_obj_key

    client, bucket = _b2()
    b2_key = drop.b2_object_key()
    try:
        obj = client.get_object(Bucket=bucket, Key=b2_key)
        raw = obj['Body'].read()
    except Exception as e:
        logger.error("switch file→text download failed for %s: %s", drop.key, e)
        return JsonResponse({'error': f'Could not read file: {e}'}, status=500)

    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError:
        return JsonResponse(
            {'error': 'File appears to be binary — cannot convert to text.'},
            status=400,
        )

    from core.views.helpers import max_text_bytes
    if len(raw) > max_text_bytes(request.user):
        return JsonResponse({'error': 'Content exceeds text size limit.'}, status=400)

    new_ns = Drop.NS_CLIPBOARD
    target_key = drop.key
    if Drop.objects.filter(ns=new_ns, key=target_key).exists():
        target_key = secrets.token_urlsafe(6)

    old_size = drop.filesize or 0
    drop.hard_delete()

    new_drop = Drop.objects.create(
        ns=new_ns, key=target_key, kind=Drop.TEXT,
        content=text, owner=request.user, locked=True,
    )

    from core.views.helpers import add_storage
    add_storage(request.user, -old_size)

    return JsonResponse({
        'key': new_drop.key, 'ns': new_drop.ns, 'kind': new_drop.kind,
        'url': f'/{new_drop.key}/',
    })