from django.contrib.auth.models import User
from django.db import models


class Plan(models.TextChoices):
    ANONYMOUS = "anonymous", "Anonymous"
    FREE = "free", "Free"
    STARTER = "starter", "Starter"
    PRO = "pro", "Pro"


LIMITS = {
    Plan.ANONYMOUS: {
        "storage_bytes": (1024**3) // 10,
        "max_file_bytes": 200 * 1024**2,
        "max_expiry_days": 1,
        "password_protected": False,
        "custom_keys": False,
        "helpbot_calls_per_hr": 3,
    },
    Plan.FREE: {
        "storage_bytes": 1 * 1024**3,
        "max_file_bytes": 200 * 1024**2,
        "max_expiry_days": 7,
        "password_protected": False,
        "custom_keys": False,
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

PRICES_CAD = {
    Plan.STARTER: 5,
    Plan.PRO: 10,
}


class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    plan = models.CharField(max_length=20, choices=Plan.choices, default=Plan.FREE)
    plan_since = models.DateTimeField(null=True, blank=True)
    storage_used = models.BigIntegerField(default=0)

    email_verified = models.BooleanField(default=False)
    temp_email = models.EmailField(blank=True, null=True)

    notify_product_updates = models.BooleanField(default=True)
    notify_billing = models.BooleanField(default=True)
    notify_bug_fix = models.BooleanField(default=True)

    ls_customer_id = models.CharField(max_length=64, blank=True, default="")
    ls_subscription_id = models.CharField(max_length=64, blank=True, default="")
    ls_subscription_status = models.CharField(max_length=32, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} ({self.plan})"

    @property
    def limits(self):
        return LIMITS[self.plan]

    @property
    def is_paid(self):
        return self.plan in (Plan.STARTER, Plan.PRO)