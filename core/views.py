import logging
import secrets

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.utils.html import strip_tags

from core.models import Plan, UserProfile, plan_display

logger = logging.getLogger(__name__)

# ── error handler ────────────────────────────────────────────────────────

_ERROR_MESSAGES = {
    400: "Bad request.",
    403: "You don't have permission to access this.",
    404: "Page not found.",
    500: "Something went wrong on our end.",
}


def error_view(request, exception=None, status=None):
    """Unified error handler for 400/403/404/500."""
    # Django passes status via the handler variable name, not as an arg.
    # Determine from caller context.
    code = status or getattr(exception, "status_code", None) or 500
    # handler404 passes the exception with no status_code attr
    if exception is not None and code == 500:
        code = 404
    if code >= 500:
        logger.error("Server error %s: %s %s", code, request.method, request.path, exc_info=exception)
    return render(request, "pages/error.html", {
        "code": code,
        "message": _ERROR_MESSAGES.get(code, "An error occurred."),
    }, status=code)


# ── helpers ──────────────────────────────────────────────────────────────

_signer = TimestampSigner(salt="email-verify")


def _send_verification_email(user):
    """Send a signed verification link to *user*."""
    token = _signer.sign(str(user.pk))
    link = f"https://{settings.DOMAIN}/auth/verify/{token}/"
    html = render_to_string("email/verify.html", {"user": user, "link": link})
    send_mail(
        subject="drp — verify your email",
        message=strip_tags(html),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        html_message=html,
        fail_silently=True,
    )


# ── auth views ───────────────────────────────────────────────────────────

def login_view(request):
    if request.user.is_authenticated:
        return redirect("account")
    if request.method == "POST":
        identifier = request.POST.get("email", "").strip()
        password = request.POST.get("password", "")
        # Allow login by username or email
        user = authenticate(request, username=identifier, password=password)
        if user is None:
            # Try email lookup
            try:
                u = User.objects.get(email=identifier)
                user = authenticate(request, username=u.username, password=password)
            except User.DoesNotExist:
                pass
        if user is not None:
            login(request, user)
            return redirect(request.GET.get("next", "/"))
        return render(request, "auth/login.html", {"error": "Invalid credentials."})
    return render(request, "auth/login.html")


def register_view(request):
    if request.user.is_authenticated:
        return redirect("account")
    ctx = {
        "free_limits": plan_display("free"),
        "starter_limits": plan_display("starter"),
        "pro_limits": plan_display("pro"),
    }
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        email = request.POST.get("email", "").strip()
        password = request.POST.get("password", "")
        password2 = request.POST.get("password2", "")
        plan_choice = request.POST.get("plan", "free")

        if not username or not email or not password:
            ctx["error"] = "All fields are required."
            return render(request, "auth/register.html", ctx)
        if password != password2:
            ctx["error"] = "Passwords do not match."
            return render(request, "auth/register.html", ctx)
        if User.objects.filter(username=username).exists():
            ctx["error"] = "That username is taken."
            return render(request, "auth/register.html", ctx)
        if User.objects.filter(email=email).exists():
            ctx["error"] = "An account with that email already exists."
            return render(request, "auth/register.html", ctx)

        user = User.objects.create_user(username=username, email=email, password=password)
        UserProfile.objects.create(user=user, plan=plan_choice)
        _send_verification_email(user)
        login(request, user)

        if plan_choice in (Plan.STARTER, Plan.PRO):
            return redirect(f"/billing/checkout/{plan_choice}/")
        return redirect("account")

    return render(request, "auth/register.html", ctx)


def logout_view(request):
    logout(request)
    return redirect("/")


# ── account ──────────────────────────────────────────────────────────────

@login_required(login_url="/auth/login/")
def account_view(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    from drive.models import Key  # avoid circular import at module level

    drops = Key.objects.filter(file__owner=request.user).select_related("file")
    return render(request, "auth/account.html", {
        "profile": profile,
        "drops": drops,
        "plan_limits": plan_display(profile.plan),
        "starter_limits": plan_display("starter"),
        "pro_limits": plan_display("pro"),
    })


@login_required(login_url="/auth/login/")
def account_settings(request):
    """POST — save notification preferences."""
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if request.method == "POST":
        profile.notify_product_updates = bool(request.POST.get("notify_product_updates"))
        profile.notify_billing = bool(request.POST.get("notify_billing"))
        profile.notify_bug_fix = bool(request.POST.get("notify_bug_fix"))
        profile.save(update_fields=[
            "notify_product_updates", "notify_billing", "notify_bug_fix",
        ])
    return redirect("account")


# ── email verification ───────────────────────────────────────────────────

def verify_email(request, token):
    """GET  /auth/verify/<token>/  — confirm email."""
    try:
        pk = _signer.unsign(token, max_age=86400)  # 24 h
    except SignatureExpired:
        return render(request, "auth/verify_expired.html", {
            "email": request.user.email if request.user.is_authenticated else "",
        })
    except BadSignature:
        return render(request, "auth/verify_invalid.html")

    try:
        user = User.objects.get(pk=int(pk))
    except User.DoesNotExist:
        return render(request, "auth/verify_invalid.html")

    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.email_verified = True
    profile.save(update_fields=["email_verified"])
    return render(request, "auth/verify_done.html")


@login_required(login_url="/auth/login/")
def verify_resend(request):
    """POST — resend verification email."""
    if request.method == "POST":
        _send_verification_email(request.user)
        return render(request, "auth/verify_resend.html", {
            "sent": True, "email": request.user.email,
        })
    return render(request, "auth/verify_resend.html", {"sent": False})
