"""
Drop template CRUD views.

Templates are reusable presets for drops (content, burn, expiry, password).
Paid users only.
"""

import json

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST

from core.models import DropTemplate, Plan
from core.views.helpers import user_plan


def _require_paid(request):
    plan = user_plan(request.user)
    if plan in (Plan.ANON, Plan.FREE):
        return JsonResponse(
            {"error": "Drop templates are a paid feature."},
            status=403,
        )
    return None


@login_required
@require_POST
def create_template(request):
    """POST /auth/templates/create/  body: {slug, name, content?, burn?, expiry_days?, password?}"""
    err = _require_paid(request)
    if err:
        return err

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON."}, status=400)

    slug = (data.get("slug") or "").strip()
    name = (data.get("name") or "").strip()
    if not slug or not name:
        return JsonResponse({"error": "slug and name are required."}, status=400)

    if DropTemplate.objects.filter(owner=request.user, slug=slug).exists():
        return JsonResponse({"error": f"Template '{slug}' already exists."}, status=409)

    tpl = DropTemplate.objects.create(
        owner=request.user,
        slug=slug,
        name=name,
        content=data.get("content", ""),
        burn=bool(data.get("burn", False)),
        expiry_days=data.get("expiry_days") or None,
        password=bool(data.get("password", False)),
    )
    return JsonResponse({
        "id": tpl.pk,
        "slug": tpl.slug,
        "name": tpl.name,
    }, status=201)


@login_required
def list_templates(request):
    """GET /auth/templates/"""
    err = _require_paid(request)
    if err:
        return err

    templates = DropTemplate.objects.filter(owner=request.user)
    return JsonResponse({
        "templates": [
            {
                "id": t.pk,
                "slug": t.slug,
                "name": t.name,
                "content": t.content[:200],
                "burn": t.burn,
                "expiry_days": t.expiry_days,
                "password": t.password,
            }
            for t in templates
        ]
    })


@login_required
def get_template(request, slug):
    """GET /auth/templates/<slug>/  — full template data for applying."""
    err = _require_paid(request)
    if err:
        return err

    tpl = get_object_or_404(DropTemplate, owner=request.user, slug=slug)
    return JsonResponse({
        "id": tpl.pk,
        "slug": tpl.slug,
        "name": tpl.name,
        "content": tpl.content,
        "burn": tpl.burn,
        "expiry_days": tpl.expiry_days,
        "password": tpl.password,
    })


@login_required
@require_POST
def delete_template(request, template_id):
    """POST /auth/templates/<id>/delete/"""
    tpl = get_object_or_404(DropTemplate, pk=template_id, owner=request.user)
    tpl.delete()
    return JsonResponse({"deleted": True})
