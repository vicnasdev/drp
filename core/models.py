"""
core/models.py  —  re-exports the canonical models so billing/help can just do:
    from core.models import UserProfile, Plan, File, Folder …

The real model definitions live here. billing.views imports Plan + UserProfile.
"""

import secrets
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


def generate_key():
    return secrets.token_urlsafe(6)   # ~8 chars, URL-safe


# ── Plan ──────────────────────────────────────────────────────────────────────

class Plan(models.TextChoices):
    ANON    = "anon",    "Anonymous"
    FREE    = "free",    "Free"
    STARTER = "starter", "Starter"
    PRO     = "pro",     "Pro"

    @classmethod
    def get(cls, plan: str, key: str, default=None):
        """Proxy to PLAN_LIMITS. Allows Plan.get(plan, 'helpbot_hourly')."""
        import sys
        limits = sys.modules[__name__].PLAN_LIMITS
        return limits.get(plan, {}).get(key, default)


PLAN_LIMITS = {
    Plan.ANON: {
        "max_file_mb":      200,
        "storage_gb":       0,
        "max_expiry_days":  1,
        "max_folders":      0,
        "price_monthly":    0,
        "can_password":     False,
        "can_custom_key":   False,
        "helpbot_hourly":   0,
    },
    Plan.FREE: {
        "max_file_mb":      200,
        "storage_gb":       1,
        "max_expiry_days":  7,
        "max_folders":      3,
        "price_monthly":    0,
        "can_password":     False,
        "can_custom_key":   True,
        "helpbot_hourly":   5,
    },
    Plan.STARTER: {
        "max_file_mb":      1024,
        "storage_gb":       5,
        "max_expiry_days":  365,
        "max_folders":      10,
        "price_monthly":    5,
        "can_password":     True,
        "can_custom_key":   True,
        "helpbot_hourly":   30,
    },
    Plan.PRO: {
        "max_file_mb":      5120,
        "storage_gb":       20,
        "max_expiry_days":  1095,
        "max_folders":      None,   # unlimited
        "price_monthly":    10,
        "can_password":     True,
        "can_custom_key":   True,
        "helpbot_hourly":   120,
    },
}

ANON_MAX_FILE_MB   = 200
ANON_LIFETIME_DAYS = 1    # 24 h
FREE_LIFETIME_DAYS = 7


# ── UserProfile ───────────────────────────────────────────────────────────────

class UserProfile(models.Model):
    user                    = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    plan                    = models.CharField(max_length=16, choices=Plan.choices, default=Plan.FREE)
    plan_since              = models.DateTimeField(null=True, blank=True)

    # Lemon Squeezy
    ls_customer_id          = models.CharField(max_length=64, blank=True)
    ls_subscription_id      = models.CharField(max_length=64, blank=True)
    ls_subscription_status  = models.CharField(max_length=32, blank=True)

    # Storage tracking (bytes)
    storage_used_bytes      = models.BigIntegerField(default=0)

    # Email verification
    email_verified          = models.BooleanField(default=False)
    email_verify_token      = models.CharField(max_length=64, blank=True)

    # Notifications
    notify_product_updates  = models.BooleanField(default=True)
    notify_billing          = models.BooleanField(default=True)
    notify_bug_fix          = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.user.username} ({self.plan})"

    # ── Helpers ───────────────────────────────────────────────────────────────

    @property
    def is_paid(self):
        return self.plan in (Plan.STARTER, Plan.PRO)

    @property
    def plan_limits(self):
        return PLAN_LIMITS.get(self.plan, PLAN_LIMITS[Plan.FREE])

    @property
    def storage_quota_bytes(self):
        return self.plan_limits["storage_gb"] * 1024 ** 3

    @property
    def storage_quota_gb(self):
        return self.plan_limits["storage_gb"]

    @property
    def storage_used_gb(self):
        return self.storage_used_bytes / 1024 ** 3

    @property
    def max_file_bytes(self):
        return self.plan_limits["max_file_mb"] * 1024 ** 2

    def has_storage_for(self, size_bytes: int) -> bool:
        return (self.storage_used_bytes + size_bytes) <= self.storage_quota_bytes


# ── File ("drop") ─────────────────────────────────────────────────────────────

class File(models.Model):
    key             = models.CharField(max_length=64, unique=True, default=generate_key, db_index=True)
    owner           = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="files")
    anon_token      = models.CharField(max_length=64, blank=True)

    # B2 / storage
    b2_name         = models.CharField(max_length=512)
    filename        = models.CharField(max_length=512)
    content_type    = models.CharField(max_length=128, default="application/octet-stream")
    size            = models.BigIntegerField(default=0)

    # Access control
    password_hash   = models.CharField(max_length=256, blank=True)
    is_public       = models.BooleanField(default=False)

    # Lifecycle
    expires_at      = models.DateTimeField(null=True, blank=True)
    burn_after_read = models.BooleanField(default=False)

    # Extras
    tags            = models.JSONField(default=list, blank=True)

    # Stats
    view_count      = models.PositiveIntegerField(default=0)
    last_viewed_at  = models.DateTimeField(null=True, blank=True)

    # Locking
    locked          = models.BooleanField(default=False)
    locked_until    = models.DateTimeField(null=True, blank=True)

    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["owner", "-created_at"]),
            models.Index(fields=["expires_at"]),
            models.Index(fields=["is_public", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.key} ({self.filename})"

    @property
    def is_expired(self):
        return self.expires_at is not None and self.expires_at <= timezone.now()

    @property
    def is_locked(self):
        if self.locked:
            return True
        if self.locked_until and self.locked_until > timezone.now():
            return True
        return False

    @property
    def is_password_protected(self):
        return bool(self.password_hash)

    @property
    def like_count(self):
        return self.likes.count()

    @property
    def filesize(self):
        """Alias used in templates."""
        return self.size


# ── Folder ────────────────────────────────────────────────────────────────────

class Folder(models.Model):
    slug        = models.SlugField(max_length=128)
    owner       = models.ForeignKey(User, on_delete=models.CASCADE, related_name="folders")
    parent      = models.ForeignKey("self", null=True, blank=True, on_delete=models.CASCADE, related_name="children")
    is_public   = models.BooleanField(default=False)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("owner", "parent", "slug")]

    def __str__(self):
        return f"@{self.owner.username}/{self.slug}"


class FolderItem(models.Model):
    folder      = models.ForeignKey(Folder, on_delete=models.CASCADE, related_name="items")
    key         = models.CharField(max_length=64, db_index=True)
    label       = models.CharField(max_length=512, blank=True)
    added_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("folder", "key")]


# ── Bookmarks ─────────────────────────────────────────────────────────────────

class FileBookmark(models.Model):
    user        = models.ForeignKey(User, on_delete=models.CASCADE, related_name="file_bookmarks")
    file_key    = models.CharField(max_length=64)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("user", "file_key")]


# ── API Tokens ────────────────────────────────────────────────────────────────

class APIToken(models.Model):
    user        = models.ForeignKey(User, on_delete=models.CASCADE, related_name="api_tokens")
    token_hash  = models.CharField(max_length=64, unique=True)
    label       = models.CharField(max_length=128, blank=True)
    last_used   = models.DateTimeField(null=True, blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} — {self.label or self.token_hash[:8]}"


# ── Engagement ────────────────────────────────────────────────────────────────

class Like(models.Model):
    file        = models.ForeignKey(File, on_delete=models.CASCADE, related_name="likes")
    user        = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    ip          = models.GenericIPAddressField(null=True, blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["file", "user"], condition=models.Q(user__isnull=False), name="unique_like_user"),
            models.UniqueConstraint(fields=["file", "ip"],   condition=models.Q(user__isnull=True),  name="unique_like_ip"),
        ]


# ── Bug reports ───────────────────────────────────────────────────────────────

class BugReport(models.Model):
    CATEGORIES = [
        ("upload",   "Upload / download"),
        ("expiry",   "Expiry / deletion"),
        ("auth",     "Login / account"),
        ("billing",  "Billing"),
        ("ui",       "UI / display"),
        ("other",    "Other"),
    ]
    user        = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    category    = models.CharField(max_length=32, choices=CATEGORIES)
    description = models.TextField()
    hide_identity = models.BooleanField(default=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.category} — {self.description[:60]}"


# ── Help bot ──────────────────────────────────────────────────────────────────

class HelpBotHistory(models.Model):
    user        = models.OneToOneField(User, on_delete=models.CASCADE, related_name="helpbot_history")
    messages    = models.JSONField(default=list)
    updated_at  = models.DateTimeField(auto_now=True)

    MAX_MESSAGES = 20

    def append(self, question: str, answer_html: str) -> None:
        msgs = self.messages or []
        msgs.append({"q": question, "a": answer_html})
        self.messages = msgs[-self.MAX_MESSAGES:]
        self.save(update_fields=["messages", "updated_at"])


# ── Crash reports ─────────────────────────────────────────────────────────────

class CrashReport(models.Model):
    fingerprint      = models.CharField(max_length=64, unique=True)
    exc_type         = models.CharField(max_length=256)
    title            = models.CharField(max_length=512)
    github_issue_url = models.URLField(blank=True)
    hit_count        = models.PositiveIntegerField(default=1)
    created_at       = models.DateTimeField(auto_now_add=True)
    last_seen_at     = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.exc_type} × {self.hit_count}"


# ── Plan limits (DB-backed, mirrors PLAN_LIMITS dict) ─────────────────────────

class PlanLimit(models.Model):
    """
    DB-backed plan limits. Used by help/views.py plans page.
    Source of truth is PLAN_LIMITS dict; this table is populated via a
    management command or migration data. Read-only from views.
    """
    TIERS = [(k, v) for k, v in Plan.choices]

    tier                = models.CharField(max_length=16, choices=TIERS, unique=True)
    storage_quota       = models.BigIntegerField(default=0)
    max_file_size       = models.BigIntegerField(default=0)
    max_expiry_days     = models.IntegerField(null=True, blank=True)
    can_password        = models.BooleanField(default=False)
    can_encrypt         = models.BooleanField(default=False)
    can_custom_key      = models.BooleanField(default=True)
    folder_quota        = models.IntegerField(null=True, blank=True)
    helpbot_hourly      = models.IntegerField(default=0)

    def __str__(self):
        return self.tier

    @classmethod
    def all_as_dicts(cls) -> dict:
        """Return {tier: {field: value}} from PLAN_LIMITS (no DB query needed)."""
        return {
            plan: limits
            for plan, limits in PLAN_LIMITS.items()
        }
