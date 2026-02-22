"""
Collection views.

URL patterns (all under /@<username>/):
  GET  /@username/                           — list user's collections (public)
  GET  /@username/<slug>/                    — view collection (public)
  POST /collections/create/                  — create collection (owner, paid)
  POST /collections/<id>/add/                — add drop to collection (owner)
  POST /collections/<id>/remove/             — remove drop from collection (owner)
  POST /collections/<id>/delete/             — delete collection (owner)
  POST /collections/<id>/rename/             — rename collection (owner)

Auth rules:
  - Anyone can view a collection page and its public drop list.
  - Password-protected drops within a collection still require the password
    when clicked through — we never bypass individual drop auth here.
  - Creating/editing collections requires login + paid plan.
  - Free users can view collections shared with them but cannot create.
"""

import re

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


def collection_view(request, username, slug):
    """GET /@username/<slug>/ — view a single collection."""
    owner      = get_object_or_404(User, username__iexact=username)
    collection = get_object_or_404(Collection, owner=owner, slug=slug)
    memberships = collection.memberships.all()

    # Resolve drops — skip any that have since been deleted
    entries = []
    for m in memberships:
        drop = m.drop
        entries.append({"membership": m, "drop": drop})

    is_own = request.user.is_authenticated and request.user.pk == owner.pk

    if 'application/json' in request.headers.get('Accept', ''):
        return JsonResponse({
            'id':   collection.pk,
            'slug': collection.slug,
            'name': collection.name,
            'drops': [{'ns': m.ns, 'key': m.key} for m in memberships],
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
    """POST /collections/create/  body: {name, slug?}"""
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

    if Collection.objects.filter(owner=request.user, slug=slug).exists():
        return JsonResponse({"error": f'You already have a collection named "{slug}".'}, status=409)

    collection = Collection.objects.create(owner=request.user, slug=slug, name=name)
    return JsonResponse({
        "id":   collection.pk,
        "slug": collection.slug,
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
