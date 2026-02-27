"""
core/views/aliases.py

Alias CRUD: create, resolve, list, delete.

POST /@<handle>/aliases/          — create an alias (owner only)
GET  /@<handle>/<alias>/resolve/  — resolve an alias to a drop (redirect)
GET  /auth/aliases/               — list user's aliases
POST /auth/aliases/<id>/delete/   — delete an alias
"""

import json

from django.http import JsonResponse, Http404
from django.shortcuts import redirect

from core.models import Alias, Drop


def create_alias(request):
    """POST /auth/aliases/create/ — create an alias for the logged-in user."""
    if request.method != "POST":
        return JsonResponse({"error": "POST required."}, status=405)
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Login required."}, status=401)

    try:
        data = json.loads(request.body) if request.body else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON."}, status=400)

    alias_name = (data.get("alias") or "").strip()
    key = (data.get("key") or "").strip()

    if not alias_name or not key:
        return JsonResponse({"error": "alias and key required."}, status=400)

    # Verify the drop exists
    if not Drop.objects.filter(key=key).exists():
        return JsonResponse({"error": "Drop not found."}, status=404)

    # Check for duplicates
    if Alias.objects.filter(owner=request.user, alias=alias_name).exists():
        return JsonResponse({"error": "Alias already exists."}, status=409)

    alias = Alias.objects.create(
        owner=request.user,
        alias=alias_name,
        key=key,
    )

    return JsonResponse({
        "id": alias.pk,
        "alias": alias.alias,
        "key": alias.key,
    }, status=201)


def list_aliases(request):
    """GET /auth/aliases/ — list aliases for the logged-in user."""
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Login required."}, status=401)

    aliases = Alias.objects.filter(owner=request.user).order_by("-created_at")
    return JsonResponse({
        "aliases": [
            {
                "id": a.pk,
                "alias": a.alias,
                "key": a.key,
                "created_at": a.created_at.isoformat(),
            }
            for a in aliases
        ],
    })


def delete_alias(request, alias_id):
    """POST /auth/aliases/<id>/delete/ — delete an alias."""
    if request.method != "POST":
        return JsonResponse({"error": "POST required."}, status=405)
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Login required."}, status=401)

    deleted, _ = Alias.objects.filter(pk=alias_id, owner=request.user).delete()
    if not deleted:
        return JsonResponse({"error": "Alias not found."}, status=404)

    return JsonResponse({"message": "Alias deleted."})


def resolve_alias(request, username, alias_name):
    """
    GET /@<username>/<alias>/ — resolve alias to the drop.
    Redirects to the drop URL.
    """
    from django.contrib.auth.models import User
    try:
        user = User.objects.get(username__iexact=username)
    except User.DoesNotExist:
        raise Http404

    alias = Alias.objects.filter(owner=user, alias=alias_name).first()
    if not alias:
        raise Http404

    return redirect(f"/{alias.key}/")
