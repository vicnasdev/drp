"""
core/api/views.py

API views consumed by the drp CLI.
All responses are JSON. Auth is via Bearer token (core.api.auth.token_required).

Method routing is done manually (no DRF) to keep dependencies minimal:
    GET    → retrieve / list
    POST   → create / action
    PATCH  → partial update
    DELETE → destroy
"""
from __future__ import annotations

import json
import time

from django.contrib.auth import authenticate
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from core.api.auth import token_required, issue_token, revoke_token
# from core.models import Drop, Folder, ShareToken, APIToken  ← uncomment & adjust to your model names


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _json(data: dict, status: int = 200) -> JsonResponse:
    return JsonResponse(data, status=status)

def _err(msg: str, status: int = 400) -> JsonResponse:
    return JsonResponse({"error": msg}, status=status)

def _body(request) -> dict:
    try:
        return json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return {}


# ---------------------------------------------------------------------------
# Ping
# ---------------------------------------------------------------------------

def ping(request):
    return _json({"status": "ok", "version": "1.0.0", "latency_ms": 0})


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

@csrf_exempt
@require_http_methods(["POST"])
def auth_login(request):
    data     = _body(request)
    username = data.get("username", "")
    password = data.get("password", "")
    user     = authenticate(request, username=username, password=password)
    if user is None:
        return _err("invalid credentials", 401)
    token = issue_token(user)
    return _json({"token": token.key, "username": user.username})


@csrf_exempt
@require_http_methods(["POST"])
@token_required
def auth_logout(request):
    revoke_token(request.auth_token)
    return _json({"status": "ok"})


@require_http_methods(["GET"])
@token_required
def auth_me(request):
    user = request.user
    # Adjust field names to match your UserProfile / plan model
    return _json({
        "username":               user.username,
        "email":                  user.email,
        "plan":                   getattr(user, "plan", "free"),
        "storage_used_display":   getattr(user, "storage_used_display", "0 B"),
        "storage_quota_display":  getattr(user, "storage_quota_display", "∞"),
        "drop_count":             getattr(user, "drop_count", 0),
        "folder_count":           getattr(user, "folder_count", 0),
    })


# ---------------------------------------------------------------------------
# Files (drops)
# ---------------------------------------------------------------------------

@csrf_exempt
@require_http_methods(["POST"])
def files_upload(request):
    # Anonymous uploads allowed — token_required NOT applied here
    # If a token is present, associate with user; otherwise anonymous.
    # TODO: pull file from request.FILES["file"], read extra fields from request.POST
    # drop = Drop.objects.create(...)
    return _err("not implemented", 501)


@csrf_exempt
@require_http_methods(["GET", "PATCH", "DELETE"])
def files_detail(request, key: str):
    if request.method == "GET":
        # TODO: Drop.objects.get(key=key) — return metadata
        return _err("not implemented", 501)

    if request.method == "PATCH":
        # Requires auth — owner only
        # TODO: rename/update fields
        return _err("not implemented", 501)

    if request.method == "DELETE":
        # Requires auth — owner only
        return _err("not implemented", 501)


@csrf_exempt
@require_http_methods(["POST"])
@token_required
def files_fork(request, key: str):
    # TODO: clone Drop(key=key) for request.user
    return _err("not implemented", 501)


# ---------------------------------------------------------------------------
# Folders
# ---------------------------------------------------------------------------

@csrf_exempt
@require_http_methods(["GET", "POST"])
@token_required
def folders_list_create(request):
    if request.method == "GET":
        # TODO: Folder.objects.filter(owner=request.user)
        return _json({"results": []})

    data = _body(request)
    # TODO: Folder.objects.create(owner=request.user, name=data["name"], slug=data.get("slug",""))
    return _err("not implemented", 501)


@csrf_exempt
@require_http_methods(["GET", "PATCH", "DELETE"])
@token_required
def folders_detail(request, folder_id: int):
    if request.method == "GET":
        return _err("not implemented", 501)
    if request.method == "PATCH":
        return _err("not implemented", 501)
    if request.method == "DELETE":
        return _err("not implemented", 501)


# ---------------------------------------------------------------------------
# Path resolver  (drp shell: cd @user/folder)
# ---------------------------------------------------------------------------

@require_http_methods(["GET"])
@token_required
def resolve(request):
    path = request.GET.get("path", "")
    # TODO: parse @username/folder-slug, return folder metadata
    return _err("not implemented", 501)


# ---------------------------------------------------------------------------
# Share tokens
# ---------------------------------------------------------------------------

@csrf_exempt
@require_http_methods(["GET", "POST"])
@token_required
def share_list_create(request):
    if request.method == "GET":
        return _json({"results": []})
    return _err("not implemented", 501)


@csrf_exempt
@require_http_methods(["DELETE"])
@token_required
def share_detail(request, token_id: int):
    return _err("not implemented", 501)


# ---------------------------------------------------------------------------
# API tokens
# ---------------------------------------------------------------------------

@csrf_exempt
@require_http_methods(["GET", "POST"])
@token_required
def tokens_list_create(request):
    if request.method == "GET":
        return _json({"results": []})
    data  = _body(request)
    label = data.get("label", "")
    # TODO: APIToken.objects.create(user=request.user, label=label)
    return _err("not implemented", 501)


@csrf_exempt
@require_http_methods(["DELETE"])
@token_required
def tokens_detail(request, token_id: int):
    # TODO: APIToken.objects.get(id=token_id, user=request.user).delete()
    return _err("not implemented", 501)