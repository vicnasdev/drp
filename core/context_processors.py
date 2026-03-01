from django.conf import settings

from core.models import ANONYMOUS_LIMITS, Plan, plan_display


def ads(request):
    return {
        "ADSENSE_CLIENT": getattr(settings, "ADSENSE_CLIENT", ""),
        "ADSENSE_SLOT": getattr(settings, "ADSENSE_SLOT", ""),
    }


def domain(request):
    return {
        "DOMAIN": getattr(settings, "DOMAIN", ""),
        "SITE_URL": getattr(settings, "SITE_URL", ""),
    }


def helpbot(request):
    return {
        "HELPBOT_ENABLED": bool(getattr(settings, "LLM_BASE_URL", "")),
    }


# ── Plan context ──────────────────────────────────────────────────────────────

def plans(request):
    """Inject plan display data into every template.

    Available in templates:
        guest_limits, free_limits, starter_limits, pro_limits
        guest_expiry, free_expiry  — short strings for footer
        expiry_options  — list for home.html expiry selector
        anon_expiry_label  — e.g. "1 day" for guest nudge
        plan_limits  — current user's plan limits
    """
    guest = plan_display("anonymous")
    guest["label"] = "Guest"
    free = plan_display(Plan.FREE)
    starter = plan_display(Plan.STARTER)
    pro = plan_display(Plan.PRO)

    ctx = {
        "guest_limits": guest,
        "free_limits": free,
        "starter_limits": starter,
        "pro_limits": pro,
        "guest_expiry": guest["expiry_display"],
        "free_expiry": free["expiry_display"],
        "anon_expiry_label": guest["expiry_display"],
    }

    user = getattr(request, "user", None)
    if user and user.is_authenticated:
        profile = getattr(user, "profile", None)
        if profile:
            if profile.is_anonymous:
                ctx["plan_limits"] = guest
                ctx["expiry_options"] = _expiry_options(guest["max_expiry_days"])
            else:
                user_lim = plan_display(profile.plan)
                ctx["plan_limits"] = user_lim
                ctx["expiry_options"] = _expiry_options(user_lim["max_expiry_days"])
    else:
        ctx["plan_limits"] = guest
        ctx["expiry_options"] = _expiry_options(guest["max_expiry_days"])

    return ctx


def _expiry_options(max_days: int) -> list[dict]:
    """Build a list of expiry options up to *max_days*."""
    all_opts = [
        (1, "1 day"),
        (7, "7 days"),
        (30, "30 days"),
        (90, "90 days"),
        (365, "1 year"),
        (365 * 3, "3 years"),
    ]
    options = []
    for days, label in all_opts:
        if days <= max_days:
            options.append({"days": days, "label": label, "selected": False})
    if options:
        options[-1]["selected"] = True
    return options
