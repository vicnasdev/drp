import secrets
from datetime import timedelta

from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone


class Plan(models.TextChoices):
    ANONYMOUS = "anonymous", "Anonymous"
    FREE = "free", "Free"
    STARTER = "starter", "Starter"
    PRO = "pro", "Pro"


LIMITS = {
    Plan.ANONYMOUS: {
        "storage_bytes": 0,
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

PRICES_CAD = {
    Plan.STARTER: 5,
    Plan.PRO: 10,
}


# ── UserProfile ───────────────────────────────────────────────────────────────

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    plan = models.CharField(max_length=20, choices=Plan.choices, default=Plan.FREE)
    plan_since = models.DateTimeField(null=True, blank=True)
    storage_used = models.BigIntegerField(default=0)

    email_verified = models.BooleanField(default=False)

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


# ── AuthToken ─────────────────────────────────────────────────────────────────

class AuthToken(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="tokens")
    key = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    def is_valid(self):
        return self.expires_at is None or timezone.now() < self.expires_at

    def __str__(self):
        return f"{self.user.username} — {self.key[:8]}..."


# ── Token utils ───────────────────────────────────────────────────────────────

def create_token(user: User, duration: timedelta | None = None) -> AuthToken:
    expires_at = timezone.now() + duration if duration else None
    return AuthToken.objects.create(
        user=user,
        key=secrets.token_hex(32),
        expires_at=expires_at,
    )


def validate_token(key: str) -> User | None:
    """Return the user if token exists and is valid, else None."""
    try:
        token = AuthToken.objects.select_related("user__profile").get(key=key)
    except AuthToken.DoesNotExist:
        return None
    if not token.is_valid():
        token.delete()
        return None
    return token.user



def is_anonymous(user: User) -> bool:
    profile = getattr(user, "profile", None)
    return profile is not None and profile.plan == Plan.ANONYMOUS


def create_guest_user() -> str:
    """Create a temporary anonymous user and return an auth token key."""
    username = f"guest_{secrets.token_hex(8)}"
    user = User.objects.create_user(username=username, password=None)
    UserProfile.objects.create(user=user, plan=Plan.ANONYMOUS)
    return create_token(user).key