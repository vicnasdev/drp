"""
core/views/auth.py

Login, logout, register, account settings, manage (drive), email verification,
export/import.
"""

import json
import re
import secrets
from datetime import timedelta

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST, require_GET
from django.conf import settings

from core.models import (
    File, FileBookmark, Folder, FolderItem, UserProfile,
    PLAN_LIMITS, FREE_LIFETIME_DAYS,
)

import logging
logger = logging.getLogger(__name__)


# ── Login ─────────────────────────────────────────────────────────────────────

def login_view(request):
    if request.user.is_authenticated:
        return redirect("home")

    if request.method == "POST":
        identifier = request.POST.get("email", "").strip()
        password   = request.POST.get("password", "")

        # Accept username or email
        user = None
        if "@" in identifier:
            try:
                u    = User.objects.get(email__iexact=identifier)
                user = authenticate(request, username=u.username, password=password)
            except User.DoesNotExist:
                pass
        if not user:
            user = authenticate(request, username=identifier, password=password)

        if user:
            login(request, user)
            return redirect(request.GET.get("next", "home"))
        return render(request, "auth/login.html", {"error": "Invalid username or password."})

    return render(request, "auth/login.html")


# ── Logout ────────────────────────────────────────────────────────────────────

def logout_view(request):
    logout(request)
    return redirect("home")


# ── Register ──────────────────────────────────────────────────────────────────

def register_view(request):
    if request.user.is_authenticated:
        return redirect("home")

    if request.method == "POST":
        username  = request.POST.get("username", "").strip()
        email     = request.POST.get("email", "").strip().lower()
        password  = request.POST.get("password", "")
        password2 = request.POST.get("password2", "")
        plan      = request.POST.get("plan", "free")

        errors = []
        if not re.match(r'^[a-zA-Z0-9_\-]{1,30}$', username):
            errors.append("Username must be 1–30 chars: letters, numbers, hyphens, underscores.")
        if User.objects.filter(username__iexact=username).exists():
            errors.append("Username already taken.")
        if User.objects.filter(email__iexact=email).exists():
            errors.append("An account with this email already exists.")
        if len(password) < 8:
            errors.append("Password must be at least 8 characters.")
        if password != password2:
            errors.append("Passwords do not match.")

        if errors:
            return render(request, "auth/register.html", {"error": " ".join(errors)})

        user = User.objects.create_user(username=username, email=email, password=password)

        # Profile is created via signal; send verification email
        _send_verify_email(user)

        login(request, user)

        # Redirect to checkout if paid plan selected
        if plan in ("starter", "pro"):
            return redirect("billing_checkout", plan=plan)

        # Claim any anon drops from session
        anon_token = request.session.get("anon_token")
        if anon_token:
            claimed = File.objects.filter(anon_token=anon_token, owner=None).update(
                owner=user, anon_token=""
            )
            if claimed:
                return redirect(f"/?claimed={claimed}")

        return redirect("home")

    return render(request, "auth/register.html")


# ── Account ───────────────────────────────────────────────────────────────────

@login_required
def account_view(request):
    profile    = request.user.profile
    drops      = File.objects.filter(owner=request.user).count()
    plan_limits = PLAN_LIMITS.get(profile.plan, PLAN_LIMITS["free"])
    ctx = {
        "profile":     profile,
        "drops":       range(drops),   # template does |length
        "plan_limits": plan_limits,
    }
    return render(request, "auth/account.html", ctx)


@login_required
@require_POST
def account_settings(request):
    profile = request.user.profile
    profile.notify_product_updates = bool(request.POST.get("notify_product_updates"))
    profile.notify_billing         = bool(request.POST.get("notify_billing"))
    profile.notify_bug_fix         = bool(request.POST.get("notify_bug_fix"))
    profile.save(update_fields=["notify_product_updates", "notify_billing", "notify_bug_fix"])
    return redirect("account")


# ── Manage / Drive ────────────────────────────────────────────────────────────

@login_required
def manage_view(request):
    # manage.html no longer exists — /@username/ (folder.html) is the drive now.
    return redirect("profile", username=request.user.username)


# ── Email verification ────────────────────────────────────────────────────────

def verify_email(request, token):
    try:
        profile = UserProfile.objects.get(email_verify_token=token)
    except UserProfile.DoesNotExist:
        return render(request, "auth/verify_invalid.html", status=400)

    if profile.email_verified:
        return render(request, "auth/verify_done.html")

    profile.email_verified    = True
    profile.email_verify_token = ""
    profile.save(update_fields=["email_verified", "email_verify_token"])
    return render(request, "auth/verify_done.html")


@login_required
@require_POST
def verify_resend(request):
    profile = request.user.profile
    if profile.email_verified:
        return redirect("account")
    _send_verify_email(request.user)
    return render(request, "auth/verify_required.html", {
        "email": request.user.email,
        "resent": True,
    })


def _send_verify_email(user):
    token = secrets.token_urlsafe(32)
    profile = user.profile
    profile.email_verify_token = token
    profile.save(update_fields=["email_verify_token"])

    site_url = getattr(settings, "SITE_URL", "http://localhost:8000")
    verify_url = f"{site_url}/auth/verify/{token}/"

    send_mail(
        subject="Verify your drp email",
        message=f"Click to verify your email:\n{verify_url}\n\nIf you didn't sign up, ignore this.",
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=settings.DEBUG,
    )


# ── Export / Import ───────────────────────────────────────────────────────────

@login_required
@require_GET
def account_export(request):
    drops = File.objects.filter(owner=request.user).values(
        "key", "filename", "content_type", "size", "expires_at", "created_at", "is_public"
    )
    bookmarks = FileBookmark.objects.filter(user=request.user).values("file_key", "created_at")

    data = {
        "version":   1,
        "exported":  timezone.now().isoformat(),
        "username":  request.user.username,
        "drops":     [
            {**d, "expires_at": d["expires_at"].isoformat() if d["expires_at"] else None,
             "created_at": d["created_at"].isoformat()}
            for d in drops
        ],
        "bookmarks": [
            {"file_key": b["file_key"], "created_at": b["created_at"].isoformat()}
            for b in bookmarks
        ],
    }
    response = HttpResponse(
        json.dumps(data, indent=2),
        content_type="application/json",
    )
    response["Content-Disposition"] = 'attachment; filename="drp-export.json"'
    return response


@login_required
@require_POST
def account_import(request):
    try:
        data = json.loads(request.body)
    except Exception:
        return JsonResponse({"error": "Invalid JSON."}, status=400)

    imported = 0
    skipped  = 0

    for bm in data.get("bookmarks", []):
        key = bm.get("file_key") or bm.get("key")
        if not key:
            continue
        _, created = FileBookmark.objects.get_or_create(user=request.user, file_key=key)
        if created:
            imported += 1
        else:
            skipped += 1

    return JsonResponse({"imported": imported, "skipped": skipped})