from django.conf import settings
from core.models import LIMITS, Plan


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


def plans(request):
    user = getattr(request, "user", None)
    profile = getattr(user, "profile", None) if user and user.is_authenticated else None
    current_plan = profile.plan if profile else Plan.ANONYMOUS

    ctx = {f"{plan.value}_limits": LIMITS[plan] for plan in Plan}
    ctx["plan_limits"] = LIMITS[current_plan]
    ctx["expiry_options"] = _expiry_options(LIMITS[current_plan]["max_expiry_days"])

    return ctx


def _expiry_label(days: int) -> str:
    if days >= 365 and days % 365 == 0:
        y = days // 365
        return f"{y} year{'s' if y != 1 else ''}"
    return f"{days} day{'s' if days != 1 else ''}"


def _expiry_options(max_days: int) -> list[dict]:
    breakpoints = sorted(set(LIMITS[plan]["max_expiry_days"] for plan in Plan))
    options = [{"days": d, "label": _expiry_label(d), "selected": False} for d in breakpoints if d <= max_days]
    if options:
        options[-1]["selected"] = True
    return options