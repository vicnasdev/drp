"""
Collection views.

URL patterns (all under /@<username>/):
  GET  /@username/                           — list user's collections (public)
  GET  /@username/<slug>/                    — view collection (public)
  POST /@username/<slug>/                    — inbox: drop into public_inbox collection (anyone)
  POST /collections/create/                  — create collection (owner, paid)
  POST /collections/<id>/add/                — add drop to collection (owner)
  POST /collections/<id>/remove/             — remove drop from collection (owner)
  POST /collections/<id>/delete/             — delete collection (owner)
  POST /collections/<id>/rename/             — rename collection (owner)
  POST /collections/<id>/toggle-inbox/       — toggle public_inbox (owner)

Auth rules:
  - Anyone can view a collection page and its public drop list.
  - Password-protected drops within a collection still require the password
    when clicked through — we never bypass individual drop auth here.
  - Creating/editing collections requires login + paid plan.
  - Free users can view collections shared with them but cannot create.
  - Anyone can POST to a public_inbox collection (text only for safety).
"""

import json
import re
import uuid

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from core.models import Collection, CollectionMembership, Drop, Plan
from core.views.helpers import user_plan


_SLUG_RE = re.compile(r'^[a-zA-Z0-9_-]{1,60}$')


def _collection_quota_ok(user):
    """Returns (ok: bool, limit: int|None)."""
    plan = user_plan(user)
    limit = Plan.get(plan, "max_collections")
    if limit is None:
        return True, None  # unlimited (Pro)
    current = Collection.objects.filter(owner=user).count()
    return current < limit, limit


# ── Public views ──────────────────────────────────────────────────────────────

def user_collections(request, username):
    """GET /@username/ — list all collections for a user."""
    owner = get_object_or_404(User, username__iexact=username)
    collections = Collection.objects.filter(owner=owner).prefetch_related("memberships")
    return render(request, "collections/list.html", {
        "owner":       owner,
        "collections": collections,
        "is_own":      request.user.is_authenticated and request.user.pk == owner.pk,
    })


def collection_view(request, username, slug, collection=None):
    """GET /@username/<path>/ — view a single collection (supports sub-collections).
       POST /@username/<path>/ — drop into public inbox (if enabled)."""
    owner = get_object_or_404(User, username__iexact=username)
    if collection is None:
        collection = get_object_or_404(Collection, owner=owner, slug=slug, parent=None)

    # ── Inbox POST (anyone can drop into public_inbox collections) ──
    if request.method == "POST":
        if not collection.public_inbox:
            return JsonResponse({"error": "This collection does not accept submissions."}, status=403)

        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JsonResponse({"error": "Invalid JSON."}, status=400)

        content = (data.get("content") or "").strip()
        if not content:
            return JsonResponse({"error": "Content is required."}, status=400)
        if len(content) > 50_000:
            return JsonResponse({"error": "Inbox drops limited to 50KB."}, status=400)

        key = uuid.uuid4().hex[:8]
        drop = Drop.objects.create(
            ns=Drop.NS_CLIPBOARD,
            key=key,
            content=content,
            kind="text",
            owner=owner,  # owned by collection owner
        )
        CollectionMembership.objects.create(
            collection=collection,
            ns=Drop.NS_CLIPBOARD,
            key=key,
        )
        return JsonResponse({"key": key, "url": f"/{key}/"}, status=201)

    # ── GET ──
    memberships = collection.memberships.all()

    # Resolve drops — skip any that have since been deleted
    entries = []
    for m in memberships:
        drop = m.drop
        entries.append({"membership": m, "drop": drop})

    is_own = request.user.is_authenticated and request.user.pk == owner.pk

    if 'application/json' in request.headers.get('Accept', ''):
        from django.conf import settings as _settings
        site = getattr(_settings, 'SITE_URL', '')
        share_url = f"{site}/@{owner.username}/{collection.full_path}/"
        qr_url = f"{site}/qr/?url={share_url}"
        children = list(collection.children.all().values_list('slug', flat=True))
        return JsonResponse({
            'id':   collection.pk,
            'slug': collection.slug,
            'path': collection.full_path,
            'name': collection.name,
            'drops': [{'ns': m.ns, 'key': m.key} for m in memberships],
            'children': children,
            'share_url': share_url,
            'qr_url': qr_url,
        })

    # Owned drops available to add (for the add-drop UI)
    addable_drops = []
    if is_own:
        existing_ns_keys = {(m.ns, m.key) for m in memberships}
        addable_drops = [
            d for d in Drop.objects.filter(owner=request.user).order_by("-created_at")
            if (d.ns, d.key) not in existing_ns_keys
        ]

    return render(request, "collections/detail.html", {
        "collection":   collection,
        "owner":        owner,
        "entries":      entries,
        "is_own":       is_own,
        "addable_drops": addable_drops,
    })


# ── Owner actions (JSON) ──────────────────────────────────────────────────────

@login_required
@require_POST
def create_collection(request):
    """POST /collections/create/  body: {name, slug?, parent_id?}"""
    import json
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON."}, status=400)

    plan = user_plan(request.user)
    if Plan.get(plan, "max_collections") == 0:
        return JsonResponse(
            {"error": "Collections are a paid feature. Upgrade to Starter or Pro."},
            status=403,
        )

    ok, limit = _collection_quota_ok(request.user)
    if not ok:
        return JsonResponse(
            {"error": f"You've reached your collection limit ({limit}). Upgrade to Pro for unlimited."},
            status=403,
        )

    name = (data.get("name") or "").strip()
    if not name:
        return JsonResponse({"error": "Collection name is required."}, status=400)
    if len(name) > 120:
        return JsonResponse({"error": "Name must be 120 characters or fewer."}, status=400)

    slug = (data.get("slug") or "").strip() or slugify(name)
    slug = slug[:60]

    if not _SLUG_RE.match(slug):
        return JsonResponse(
            {"error": "Slug may only contain letters, numbers, hyphens and underscores."},
            status=400,
        )

    # Optional parent for sub-collections
    parent = None
    parent_id = data.get("parent_id")
    if parent_id:
        parent = Collection.objects.filter(pk=parent_id, owner=request.user).first()
        if not parent:
            return JsonResponse({"error": "Parent collection not found."}, status=404)

    if Collection.objects.filter(owner=request.user, parent=parent, slug=slug).exists():
        return JsonResponse({"error": f'You already have a collection named "{slug}" at this level.'}, status=409)

    collection = Collection.objects.create(
        owner=request.user, slug=slug, name=name, parent=parent,
    )
    return JsonResponse({
        "id":   collection.pk,
        "slug": collection.slug,
        "path": collection.full_path,
        "name": collection.name,
        "url":  collection.url_path,
    }, status=201)


@login_required
@require_POST
def add_to_collection(request, collection_id):
    """POST /collections/<id>/add/  body: {ns, key}"""
    import json
    collection = get_object_or_404(Collection, pk=collection_id)
    if not collection.can_edit(request.user):
        return JsonResponse({"error": "Only the owner can edit this collection."}, status=403)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON."}, status=400)

    ns  = data.get("ns", Drop.NS_CLIPBOARD)
    key = (data.get("key") or "").strip()

    if ns not in (Drop.NS_CLIPBOARD, Drop.NS_FILE):
        return JsonResponse({"error": "Invalid ns."}, status=400)
    if not key:
        return JsonResponse({"error": "key is required."}, status=400)
    if not Drop.objects.filter(ns=ns, key=key).exists():
        return JsonResponse({"error": "Drop not found."}, status=404)

    _, created = CollectionMembership.objects.get_or_create(
        collection=collection, ns=ns, key=key
    )
    return JsonResponse({"added": True, "created": created})


@login_required
@require_POST
def remove_from_collection(request, collection_id):
    """POST /collections/<id>/remove/  body: {ns, key}"""
    import json
    collection = get_object_or_404(Collection, pk=collection_id)
    if not collection.can_edit(request.user):
        return JsonResponse({"error": "Only the owner can edit this collection."}, status=403)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON."}, status=400)

    ns  = data.get("ns", Drop.NS_CLIPBOARD)
    key = (data.get("key") or "").strip()

    deleted, _ = CollectionMembership.objects.filter(
        collection=collection, ns=ns, key=key
    ).delete()
    return JsonResponse({"removed": bool(deleted)})


@login_required
@require_POST
def rename_collection(request, collection_id):
    """POST /collections/<id>/rename/  body: {name, slug?}"""
    import json
    collection = get_object_or_404(Collection, pk=collection_id)
    if not collection.can_edit(request.user):
        return JsonResponse({"error": "Only the owner can rename this collection."}, status=403)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON."}, status=400)

    name = (data.get("name") or "").strip()
    if not name:
        return JsonResponse({"error": "Name is required."}, status=400)
    if len(name) > 120:
        return JsonResponse({"error": "Name must be 120 characters or fewer."}, status=400)

    new_slug = (data.get("slug") or "").strip() or slugify(name)
    new_slug = new_slug[:60]

    if not _SLUG_RE.match(new_slug):
        return JsonResponse({"error": "Slug may only contain letters, numbers, hyphens and underscores."}, status=400)

    if new_slug != collection.slug:
        if Collection.objects.filter(owner=request.user, slug=new_slug).exists():
            return JsonResponse({"error": f'You already have a collection named "{new_slug}".'}, status=409)

    collection.name = name
    collection.slug = new_slug
    collection.save(update_fields=["name", "slug"])

    return JsonResponse({
        "name": collection.name,
        "slug": collection.slug,
        "url":  collection.url_path,
    })


@login_required
@require_POST
def delete_collection(request, collection_id):
    """POST /collections/<id>/delete/"""
    collection = get_object_or_404(Collection, pk=collection_id)
    if not collection.can_edit(request.user):
        return JsonResponse({"error": "Only the owner can delete this collection."}, status=403)

    collection.delete()
    return JsonResponse({"deleted": True})


@login_required
@require_POST
def toggle_inbox(request, collection_id):
    """POST /collections/<id>/toggle-inbox/ — toggle public_inbox flag."""
    collection = get_object_or_404(Collection, pk=collection_id)
    if not collection.can_edit(request.user):
        return JsonResponse({"error": "Only the owner can change inbox settings."}, status=403)
    collection.public_inbox = not collection.public_inbox
    collection.save(update_fields=["public_inbox"])
    return JsonResponse({
        "public_inbox": collection.public_inbox,
        "message": "Inbox enabled." if collection.public_inbox else "Inbox disabled.",
    })


def collection_or_alias_view(request, username, path):
    """
    GET /@username/<path>/
    Resolve a collection path (supports nested sub-collections like parent/child).
    Falls back to alias resolution for single-segment paths.
    """
    from django.http import Http404
    try:
        owner = User.objects.get(username__iexact=username)
    except User.DoesNotExist:
        raise Http404

    collection = Collection.resolve_path(owner, path)
    if collection:
        return collection_view(request, username, collection.slug, collection=collection)

    # Single-segment path → try alias resolution
    segments = [s for s in path.strip('/').split('/') if s]
    if len(segments) == 1:
        from core.views.aliases import resolve_alias
        return resolve_alias(request, username, segments[0])

    raise Http404
