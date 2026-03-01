from django.conf import settings
from django.contrib.auth.models import User
from django.db import models


class Plan(models.TextChoices):
    FREE = "free", "Free"
    STARTER = "starter", "Starter"
    PRO = "pro", "Pro"

    @classmethod
    def limits(cls, plan):
        """Return limits dict for *plan*, falling back to hardcoded defaults."""
        try:
            row = PlanLimits.objects.get(plan=plan)
            return row.as_dict()
        except (PlanLimits.DoesNotExist, Exception):
            return _DEFAULT_LIMITS.get(plan, _DEFAULT_LIMITS[cls.FREE])


# ── Hardcoded fallback (seed values + safety net) ─────────────────────────────

_DEFAULT_LIMITS = {
    Plan.FREE: {
        "storage_bytes": 1 * 1024**3,
        "max_file_bytes": 200 * 1024**2,
        "max_expiry_days": 7,
        "password_protected": False,
        "custom_keys": True,
        "helpbot_calls_per_hr": 5,
    },
    Plan.STARTER: {
        "storage_bytes": 5 * 1024**3,
        "max_file_bytes": 1 * 1024**3,
        "max_expiry_days": 365,
        "password_protected": True,
        "custom_keys": True,
        "helpbot_calls_per_hr": 30,
    },
    Plan.PRO: {
        "storage_bytes": 20 * 1024**3,
        "max_file_bytes": 5 * 1024**3,
        "max_expiry_days": 365 * 3,
        "password_protected": True,
        "custom_keys": True,
        "helpbot_calls_per_hr": 120,
    },
}


class PlanLimits(models.Model):
    """Admin-editable limits per plan.  One row per plan tier."""

    plan = models.CharField(max_length=20, choices=Plan.choices, unique=True)
    storage_bytes = models.BigIntegerField(help_text="Total storage in bytes")
    max_file_bytes = models.BigIntegerField(help_text="Max single file size in bytes")
    max_expiry_days = models.IntegerField(help_text="Max key expiry in days")
    password_protected = models.BooleanField(default=False)
    custom_keys = models.BooleanField(default=True)
    helpbot_calls_per_hr = models.IntegerField(default=5)

    class Meta:
        verbose_name = "plan limits"
        verbose_name_plural = "plan limits"

    def __str__(self):
        return f"{self.get_plan_display()} limits"

    def as_dict(self) -> dict:
        return {
            "storage_bytes": self.storage_bytes,
            "max_file_bytes": self.max_file_bytes,
            "max_expiry_days": self.max_expiry_days,
            "password_protected": self.password_protected,
            "custom_keys": self.custom_keys,
            "helpbot_calls_per_hr": self.helpbot_calls_per_hr,
        }


class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    plan = models.CharField(max_length=20, choices=Plan.choices, default=Plan.FREE)
    plan_since = models.DateTimeField(null=True, blank=True)
    is_anonymous = models.BooleanField(default=False)
    storage_used = models.BigIntegerField(default=0)

    # Lemon Squeezy
    ls_customer_id = models.CharField(max_length=64, blank=True, default="")
    ls_subscription_id = models.CharField(max_length=64, blank=True, default="")
    ls_subscription_status = models.CharField(max_length=32, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} ({self.plan})"

    @property
    def limits(self):
        return Plan.limits(self.plan)

    @property
    def is_paid(self):
        return self.plan in (Plan.STARTER, Plan.PRO)

    @property
    def storage_used_gb(self):
        return round(self.storage_used / (1024**3), 2)


# ── Anonymous plan defaults (not a Plan choice — enforced in views) ───────────

ANONYMOUS_LIMITS = {
    "storage_bytes": 0,
    "max_file_bytes": 200 * 1024**2,
    "max_expiry_days": 1,
    "password_protected": False,
    "custom_keys": False,
    "helpbot_calls_per_hr": 3,
}

# Prices are display-only; billing is handled via Lemon Squeezy.
_PLAN_PRICES_CAD = {
    Plan.STARTER: 5,
    Plan.PRO: 10,
}


def _expiry_display(days):
    """Human-readable expiry string from a day count."""
    if days is None:
        return "never"
    if days >= 365:
        years = days // 365
        return f"{years} year{'s' if years != 1 else ''}"
    return f"{days} day{'s' if days != 1 else ''}"


def plan_display(plan_key):
    """Return a display-ready dict for a plan tier (or 'anonymous')."""
    if plan_key == "anonymous":
        raw = ANONYMOUS_LIMITS
    else:
        raw = Plan.limits(plan_key)
    return {
        **raw,
        "plan": plan_key,
        "label": plan_key.capitalize(),
        "max_file_mb": round(raw["max_file_bytes"] / (1024**2)),
        "storage_gb": round(raw["storage_bytes"] / (1024**3)),
        "price_monthly": _PLAN_PRICES_CAD.get(plan_key),
        "expiry_display": _expiry_display(raw["max_expiry_days"]),
    }