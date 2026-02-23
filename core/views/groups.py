"""
Group views.

URL patterns:
  GET  /@handle/                        — resolve @handle to user or group
  POST /groups/create/                  — create a group (paid)
  POST /groups/<id>/invite/             — generate invite token (admin)
  POST /groups/join/                    — join via invite token
  POST /groups/<id>/members/<uid>/role/ — change a member's role (admin)
  POST /groups/<id>/members/<uid>/remove/ — remove a member (admin)
  GET  /groups/<id>/                    — group detail (members only?)

Auth rules:
  - Free users can join groups but cannot create/own them.
  - Only group admins can invite, change roles, remove members.
  - Non-members see "enter invite token" prompt.
"""

import secrets

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.models import (
    Group, GroupMembership, GroupInviteToken,
    Plan, Collection,
)
from core.views.helpers import user_plan


def _group_quota_ok(user):
    """Check if user can create another group."""
    plan = user_plan(user)
    limit = Plan.get(plan, "max_groups")
    if limit is None:
        return True, None  # unlimited
    current = Group.objects.filter(created_by=user).count()
    return current < limit, limit


def _is_group_admin(user, group):
    """Check if user is an admin of the group."""
    return GroupMembership.objects.filter(
        group=group, user=user, role=GroupMembership.ROLE_ADMIN
    ).exists()


def _is_group_member(user, group):
    """Check if user is any role in the group."""
    return GroupMembership.objects.filter(group=group, user=user).exists()


# ── Handle resolution ─────────────────────────────────────────────────────────

def resolve_handle(request, handle):
    """
    GET /@handle/ — resolve to user or group.
    Users take priority. If no user found, check groups.
    """
    # Try user first
    try:
        user = User.objects.get(username__iexact=handle)
        # Delegate to user_collections view
        from core.views.collections import user_collections
        return user_collections(request, handle)
    except User.DoesNotExist:
        pass

    # Try group
    try:
        group = Group.objects.get(handle__iexact=handle)
        return group_detail(request, group)
    except Group.DoesNotExist:
        pass

    from django.http import Http404
    raise Http404(f"@{handle} not found")


def group_detail(request, group):
    """Display group page — members see drops/collections, non-members see join prompt."""
    is_member = (
        request.user.is_authenticated
        and _is_group_member(request.user, group)
    )
    is_admin = (
        request.user.is_authenticated
        and _is_group_admin(request.user, group)
    )

    members = []
    collections = []
    if is_member:
        members = GroupMembership.objects.filter(group=group).select_related("user")
        collections = Collection.objects.filter(owner_group=group)

    if "application/json" in request.headers.get("Accept", ""):
        data = {
            "handle": group.handle,
            "name": group.name,
            "is_member": is_member,
            "is_admin": is_admin,
        }
        if is_member:
            data["members"] = [
                {"username": m.user.username, "role": m.role}
                for m in members
            ]
        return JsonResponse(data)

    return render(request, "groups/detail.html", {
        "group": group,
        "is_member": is_member,
        "is_admin": is_admin,
        "members": members,
        "collections": collections,
    })


# ── Create group ──────────────────────────────────────────────────────────────

@login_required
@require_POST
def create_group(request):
    """POST /groups/create/ — create a new group (paid only)."""
    import json
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON."}, status=400)

    handle = (data.get("handle") or "").strip().lower()
    name = (data.get("name") or handle).strip()

    if not handle or len(handle) > 60:
        return JsonResponse({"error": "Handle is required (max 60 chars)."}, status=400)

    # Check plan limits
    ok, limit = _group_quota_ok(request.user)
    if not ok:
        return JsonResponse(
            {"error": f"Group limit reached ({limit}). Upgrade your plan."},
            status=403,
        )

    # Check handle availability (no conflict with existing users or groups)
    if User.objects.filter(username__iexact=handle).exists():
        return JsonResponse({"error": "This handle is taken by a user."}, status=409)
    if Group.objects.filter(handle__iexact=handle).exists():
        return JsonResponse({"error": "This handle is already taken."}, status=409)

    group = Group.objects.create(
        handle=handle,
        name=name,
        created_by=request.user,
    )

    # Creator becomes admin
    GroupMembership.objects.create(
        group=group,
        user=request.user,
        role=GroupMembership.ROLE_ADMIN,
    )

    return JsonResponse({
        "id": group.pk,
        "handle": group.handle,
        "name": group.name,
        "message": f"Group @{group.handle} created.",
    }, status=201)


# ── Invite ────────────────────────────────────────────────────────────────────

@login_required
@require_POST
def create_invite(request, group_id):
    """POST /groups/<id>/invite/ — generate an invite token (admin only)."""
    group = get_object_or_404(Group, pk=group_id)

    if not _is_group_admin(request.user, group):
        return JsonResponse({"error": "Only admins can create invites."}, status=403)

    import json
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        data = {}

    role = data.get("role", GroupMembership.ROLE_READER)
    if role not in dict(GroupMembership.ROLE_CHOICES):
        return JsonResponse({"error": "Invalid role."}, status=400)

    max_uses = data.get("max_uses", 1)
    expires_hours = data.get("expires_hours", 72)  # default 3 days

    token = secrets.token_urlsafe(32)
    invite = GroupInviteToken.objects.create(
        group=group,
        token=token,
        role=role,
        created_by=request.user,
        max_uses=max_uses if max_uses else None,
        expires_at=timezone.now() + timezone.timedelta(hours=expires_hours) if expires_hours else None,
    )

    from django.conf import settings
    site = getattr(settings, 'SITE_URL', '')
    join_url = f"{site}/groups/join/?token={token}"
    qr_url = f"{site}/qr/?url={join_url}"

    return JsonResponse({
        "token": token,
        "role": invite.role,
        "max_uses": invite.max_uses,
        "expires_at": invite.expires_at.isoformat() if invite.expires_at else None,
        "join_url": join_url,
        "qr_url": qr_url,
        "message": f"Invite token created for @{group.handle}.",
    }, status=201)


# ── Join ──────────────────────────────────────────────────────────────────────

@login_required
@require_POST
def join_group(request):
    """POST /groups/join/ — join a group via invite token."""
    import json
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON."}, status=400)

    token_str = (data.get("token") or "").strip()
    if not token_str:
        return JsonResponse({"error": "Invite token required."}, status=400)

    invite = GroupInviteToken.objects.filter(token=token_str).first()
    if not invite:
        return JsonResponse({"error": "Invalid invite token."}, status=404)

    if invite.is_expired():
        return JsonResponse({"error": "This invite has expired."}, status=410)

    group = invite.group

    # Already a member?
    if _is_group_member(request.user, group):
        return JsonResponse({"error": "You are already a member."}, status=409)

    GroupMembership.objects.create(
        group=group,
        user=request.user,
        role=invite.role,
    )

    # Increment use count
    invite.use_count += 1
    invite.save(update_fields=["use_count"])

    return JsonResponse({
        "group": group.handle,
        "role": invite.role,
        "message": f"Joined @{group.handle} as {invite.role}.",
    })


# ── Member management ────────────────────────────────────────────────────────

@login_required
@require_POST
def change_member_role(request, group_id, user_id):
    """POST /groups/<id>/members/<uid>/role/ — change role (admin only)."""
    group = get_object_or_404(Group, pk=group_id)

    if not _is_group_admin(request.user, group):
        return JsonResponse({"error": "Only admins can change roles."}, status=403)

    membership = GroupMembership.objects.filter(group=group, user_id=user_id).first()
    if not membership:
        return JsonResponse({"error": "User is not a member."}, status=404)

    import json
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON."}, status=400)

    new_role = data.get("role", "").strip()
    if new_role not in dict(GroupMembership.ROLE_CHOICES):
        return JsonResponse({"error": "Invalid role."}, status=400)

    membership.role = new_role
    membership.save(update_fields=["role"])

    return JsonResponse({
        "user": membership.user.username,
        "role": new_role,
        "message": f"Role updated to {new_role}.",
    })


@login_required
@require_POST
def remove_member(request, group_id, user_id):
    """POST /groups/<id>/members/<uid>/remove/ — remove member (admin only)."""
    group = get_object_or_404(Group, pk=group_id)

    if not _is_group_admin(request.user, group):
        return JsonResponse({"error": "Only admins can remove members."}, status=403)

    # Can't remove yourself if you're the only admin
    if user_id == request.user.pk:
        admin_count = GroupMembership.objects.filter(
            group=group, role=GroupMembership.ROLE_ADMIN
        ).count()
        if admin_count <= 1:
            return JsonResponse(
                {"error": "Cannot remove the last admin."}, status=400
            )

    membership = GroupMembership.objects.filter(group=group, user_id=user_id).first()
    if not membership:
        return JsonResponse({"error": "User is not a member."}, status=404)

    membership.delete()
    return JsonResponse({"message": "Member removed."})
