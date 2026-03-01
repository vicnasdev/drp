from django.conf import settings
from django.contrib.auth.models import User
from django.db import models


class Plan(models.TextChoices):
    FREE = "free", "Free"
    STARTER = "starter", "Starter"
    PRO = "pro", "Pro"

    @classmethod
    def limits(cls, plan):
        return PLAN_LIMITS.get(plan, PLAN_LIMITS[cls.FREE])


PLAN_LIMITS = {
    Plan.FREE: {
        "storage_bytes": 1 * 1024**3,
        "max_file_bytes": 200 * 1024**2,
        "max_expiry_days": 7,
        "max_folders": 3,
        "password_protected": False,
        "custom_keys": True,
        "helpbot_calls_per_hr": 5,
    },
    Plan.STARTER: {
        "storage_bytes": 5 * 1024**3,
        "max_file_bytes": 1 * 1024**3,
        "max_expiry_days": 365,
        "max_folders": 10,
        "password_protected": True,
        "custom_keys": True,
        "helpbot_calls_per_hr": 30,
    },
    Plan.PRO: {
        "storage_bytes": 20 * 1024**3,
        "max_file_bytes": 5 * 1024**3,
        "max_expiry_days": 365 * 3,
        "max_folders": None,  # unlimited
        "password_protected": True,
        "custom_keys": True,
        "helpbot_calls_per_hr": 120,
    },
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