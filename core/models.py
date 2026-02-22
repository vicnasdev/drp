from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.utils import timezone
from datetime import timedelta
import logging

logger = logging.getLogger(__name__)


# ── Plans ─────────────────────────────────────────────────────────────────────

class Plan:
    ANON    = "anon"
    FREE    = "free"
    STARTER = "starter"
    PRO     = "pro"

    LIMITS = {
        ANON: {
            "label":                      "Anonymous",
            "price_monthly":              0,
            "max_file_mb":                200,
            "max_text_kb":                500,
            # No user-settable expiry date; clipboard drops expire by idle/max rules.
            "max_expiry_days":            None,
            # Clipboard drops: 24 h idle window, 7-day hard ceiling.
            "clipboard_idle_hours":       24,
            "clipboard_max_lifetime_days": 7,
            # File drops: hard ceiling from creation date. None = never expire.
            "anon_file_lifetime_days":    90,
            "storage_gb":                 None,
            "renewals":                   0,
            "password_protection":        False,
            "max_collections":            0,
        },
        FREE: {
            "label":                      "Free",
            "price_monthly":              0,
            "max_file_mb":                200,
            "max_text_kb":                500,
            # No user-settable expiry date; clipboard drops expire by idle/max rules.
            "max_expiry_days":            None,
            # Clipboard drops: 48 h idle window, 30-day hard ceiling.
            "clipboard_idle_hours":       48,
            "clipboard_max_lifetime_days": 30,
            # File drops: hard ceiling from creation date. None = never expire.
            "anon_file_lifetime_days":    90,
            "storage_gb":                 None,
            "renewals":                   0,
            "password_protection":        False,
            "max_collections":            0,
        },
        STARTER: {
            "label":                      "Starter",
            "price_monthly":              3,
            "max_file_mb":                1024,
            "max_text_kb":                2048,
            "max_expiry_days":            365,
            "clipboard_idle_hours":       None,   # explicit expiry only
            "clipboard_max_lifetime_days": None,  # explicit expiry only
            "anon_file_lifetime_days":    None,   # never expire by time (quota is the limit)
            "storage_gb":                 5,
            "renewals":                   None,   # unlimited
            "password_protection":        True,
            "max_collections":            10,
        },
        PRO: {
            "label":                      "Pro",
            "price_monthly":              8,
            "max_file_mb":                5120,
            "max_text_kb":                10240,
            "max_expiry_days":            365 * 3,
            "clipboard_idle_hours":       None,
            "clipboard_max_lifetime_days": None,
            "anon_file_lifetime_days":    None,   # never expire by time (quota is the limit)
            "storage_gb":                 20,
            "renewals":                   None,   # unlimited
            "password_protection":        True,
            "max_collections":            None,   # unlimited
        },
    }

    @classmethod
    def get(cls, plan_key, field):
        """Read a plan limit. Checks DB first (with in-process cache), falls back to LIMITS dict."""
        return PlanLimit.get(plan_key, field)


# ── PlanLimit (DB-backed limits) ──────────────────────────────────────────────

_plan_limit_cache: dict = {}


class PlanLimit(models.Model):
    """
    One row per plan. Limits that were hardcoded in Plan.LIMITS are now rows here.
    Edit via Django admin or data migrations — no code deploy needed.
    """
    plan = models.CharField(max_length=16, unique=True)

    label         = models.CharField(max_length=64)
    price_monthly = models.PositiveIntegerField(default=0)

    max_file_mb                = models.PositiveIntegerField(null=True, blank=True)
    max_text_kb                = models.PositiveIntegerField(null=True, blank=True)
    max_expiry_days            = models.PositiveIntegerField(null=True, blank=True)
    clipboard_idle_hours       = models.PositiveIntegerField(null=True, blank=True)
    clipboard_max_lifetime_days = models.PositiveIntegerField(null=True, blank=True)
    anon_file_lifetime_days    = models.PositiveIntegerField(null=True, blank=True,
                                     help_text="Hard ceiling (days from creation) for file drops with no explicit expiry. null = never expire (paid plans).")
    storage_gb                 = models.PositiveIntegerField(null=True, blank=True)
    renewals                   = models.PositiveIntegerField(null=True, blank=True,
                                     help_text="null = unlimited, 0 = none")
    password_protection        = models.BooleanField(default=False)
    max_collections            = models.PositiveIntegerField(null=True, blank=True,
                                     help_text="null = unlimited, 0 = none")

    class Meta:
        ordering = ["price_monthly"]

    def __str__(self):
        return f"{self.plan} (${self.price_monthly}/mo)"

    def as_dict(self) -> dict:
        return {
            "label":                       self.label,
            "price_monthly":               self.price_monthly,
            "max_file_mb":                 self.max_file_mb,
            "max_text_kb":                 self.max_text_kb,
            "max_expiry_days":             self.max_expiry_days,
            "clipboard_idle_hours":        self.clipboard_idle_hours,
            "clipboard_max_lifetime_days": self.clipboard_max_lifetime_days,
            "anon_file_lifetime_days":     self.anon_file_lifetime_days,
            "storage_gb":                  self.storage_gb,
            "renewals":                    self.renewals,
            "password_protection":         self.password_protection,
            "max_collections":             self.max_collections,
        }

    @classmethod
    def _load_cache(cls):
        global _plan_limit_cache
        try:
            _plan_limit_cache = {row.plan: row.as_dict() for row in cls.objects.all()}
        except Exception:
            # Table may not exist yet during first migrate — fall back to hardcoded dict
            _plan_limit_cache = dict(Plan.LIMITS)

    @classmethod
    def invalidate_cache(cls):
        global _plan_limit_cache
        _plan_limit_cache = {}

    @classmethod
    def get(cls, plan_key, field):
        if not _plan_limit_cache:
            cls._load_cache()
        limits = _plan_limit_cache.get(plan_key, _plan_limit_cache.get(Plan.ANON, {}))
        return limits.get(field)

    @classmethod
    def all_as_dicts(cls) -> dict:
        """Return {plan_key: {field: value}} — used by the help page."""
        if not _plan_limit_cache:
            cls._load_cache()
        return dict(_plan_limit_cache)


# ── UserProfile ───────────────────────────────────────────────────────────────

class UserProfile(models.Model):
    PLAN_CHOICES = [
        (Plan.FREE,    "Free"),
        (Plan.STARTER, "Starter ($3/mo)"),
        (Plan.PRO,     "Pro ($8/mo)"),
    ]

    user               = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    plan               = models.CharField(max_length=16, choices=PLAN_CHOICES, default=Plan.FREE)
    plan_since         = models.DateTimeField(null=True, blank=True)
    email_verified     = models.BooleanField(default=False)
    storage_used_bytes = models.PositiveBigIntegerField(default=0)

    ls_customer_id         = models.CharField(max_length=64, blank=True, default="",
                                              help_text="Lemon Squeezy customer ID")
    ls_subscription_id     = models.CharField(max_length=64, blank=True, default="",
                                              help_text="Lemon Squeezy subscription ID")
    ls_subscription_status = models.CharField(max_length=32, blank=True, default="",
                                              help_text="active, cancelled, expired, etc.")

    notify_bug_fix = models.BooleanField(
        default=True,
        help_text="Send an email when a bug the user reported is fixed (GitHub issue closed).",
    )
    notify_product_updates = models.BooleanField(
        default=True,
        help_text="Changelog, new features, and product announcements.",
    )
    notify_billing = models.BooleanField(
        default=True,
        help_text="Payment receipts, failed charges, and plan change confirmations.",
    )

    is_test = models.BooleanField(default=False, db_index=True,
                                  help_text="Created by the integration test suite. Purged at deploy.")

    def __str__(self):
        return f"{self.user.username} [{self.plan}]"

    @property
    def is_paid(self):
        return self.plan in (Plan.STARTER, Plan.PRO)

    @property
    def storage_quota_bytes(self):
        gb = Plan.get(self.plan, "storage_gb")
        return gb * 1024 ** 3 if gb else None

    @property
    def storage_used_gb(self):
        return self.storage_used_bytes / (1024 ** 3)

    @property
    def storage_quota_gb(self):
        return Plan.get(self.plan, "storage_gb")

    def storage_available_bytes(self):
        quota = self.storage_quota_bytes
        return max(0, quota - self.storage_used_bytes) if quota is not None else None

    def recalc_storage(self):
        total = self.user.drops.aggregate(total=models.Sum("filesize"))["total"] or 0
        UserProfile.objects.filter(pk=self.pk).update(storage_used_bytes=total)
        self.storage_used_bytes = total

    def max_expiry_days(self):
        return Plan.get(self.plan, "max_expiry_days")

    def max_file_mb(self):
        return Plan.get(self.plan, "max_file_mb")

    def max_text_kb(self):
        return Plan.get(self.plan, "max_text_kb")


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.get_or_create(user=instance)



# ── Drop ──────────────────────────────────────────────────────────────────────

class Drop(models.Model):
    NS_CLIPBOARD = "c"
    NS_FILE      = "f"
    NS_CHOICES   = [("c", "Clipboard"), ("f", "File")]

    TEXT = "text"
    FILE = "file"
    TYPE_CHOICES = [(TEXT, "Text"), (FILE, "File")]

    ns   = models.CharField(max_length=1, choices=NS_CHOICES, default=NS_CLIPBOARD, db_index=True)
    key  = models.CharField(max_length=120, db_index=True)
    kind = models.CharField(max_length=4, choices=TYPE_CHOICES)

    owner = models.ForeignKey(
        User, null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="drops",
    )

    anon_token = models.CharField(max_length=64, null=True, blank=True, db_index=True)

    content = models.TextField(blank=True, default="")

    file_url       = models.URLField(blank=True, default="")
    file_public_id = models.CharField(max_length=512, blank=True, default="")
    filename       = models.CharField(max_length=255, blank=True, default="")
    filesize       = models.PositiveBigIntegerField(default=0)
    content_type   = models.CharField(max_length=255, blank=True, default="")

    created_at        = models.DateTimeField(auto_now_add=True)
    last_accessed_at  = models.DateTimeField(null=True, blank=True, db_index=True)
    max_lifetime_secs = models.PositiveIntegerField(null=True, blank=True)

    locked        = models.BooleanField(default=False)
    locked_until  = models.DateTimeField(null=True, blank=True)
    expires_at    = models.DateTimeField(null=True, blank=True)
    renewal_count = models.PositiveIntegerField(default=0)

    burn = models.BooleanField(default=False, help_text="Delete after first view")

    is_test = models.BooleanField(default=False, db_index=True,
                                  help_text="Created by the integration test suite. Purged at deploy.")

    # ── Password protection (paid accounts only) ──────────────────────────────
    # Stored as a Django password hash (PBKDF2). Never stored in plaintext.
    # None = no password. Set/change/remove only by the owner on a paid plan.
    password_hash = models.CharField(max_length=256, blank=True, default="",
                                     help_text="PBKDF2 hash. Empty = no password.")

    # ── View tracking ─────────────────────────────────────────────────────────
    view_count     = models.PositiveIntegerField(default=0)
    last_viewed_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        unique_together = [("ns", "key")]

    def __str__(self):
        prefix = "f/" if self.ns == self.NS_FILE else ""
        return f"/{prefix}{self.key}/ ({self.kind})"

    @property
    def is_password_protected(self):
        return bool(self.password_hash)

    def check_password(self, raw_password: str) -> bool:
        from django.contrib.auth.hashers import check_password
        return check_password(raw_password, self.password_hash)

    def set_password(self, raw_password: str | None) -> None:
        """Set or clear the drop password. Call save() after."""
        if raw_password:
            from django.contrib.auth.hashers import make_password
            self.password_hash = make_password(raw_password)
        else:
            self.password_hash = ""

    @property
    def owner_plan(self):
        if self.owner_id and hasattr(self.owner, "profile"):
            return self.owner.profile.plan
        return Plan.ANON

    @property
    def is_paid_drop(self):
        if self.owner_id and hasattr(self.owner, "profile"):
            return self.owner.profile.is_paid
        return False

    def is_expired(self):
        now = timezone.now()

        if self.expires_at:
            return now > self.expires_at

        if self.max_lifetime_secs:
            if (now - self.created_at).total_seconds() > self.max_lifetime_secs:
                return True

        if self.ns == self.NS_CLIPBOARD:
            plan = self.owner_plan if self.owner_id else Plan.ANON
            idle_hours = Plan.get(plan, "clipboard_idle_hours") or 24
            ref = self.last_accessed_at or self.created_at
            return (now - ref) > timedelta(hours=idle_hours)

        # File drop fallback: check plan's anon_file_lifetime_days.
        # Paid plans return None (never expire by time — quota is the constraint).
        plan = self.owner_plan if self.owner_id else Plan.ANON
        max_days = Plan.get(plan, "anon_file_lifetime_days")
        if max_days is None:
            return False
        return (now - self.created_at) > timedelta(days=max_days)

    TOUCH_DEBOUNCE_SECS = 300  # 5 minutes

    def touch(self):
        now = timezone.now()
        if (
            self.last_accessed_at is not None
            and (now - self.last_accessed_at).total_seconds() < self.TOUCH_DEBOUNCE_SECS
        ):
            return
        Drop.objects.filter(pk=self.pk).update(
            last_accessed_at=now,
            last_viewed_at=now,
            view_count=models.F("view_count") + 1,
        )
        self.last_accessed_at = now
        self.last_viewed_at   = now
        self.view_count      += 1

    def renew(self):
        if not self.expires_at:
            return
        duration = self.expires_at - self.created_at
        # Extend from whichever is later — the current expiry or now.
        # Using max() guarantees the new expiry is always strictly greater
        # than the old one, even when the drop was just created.
        self.expires_at = max(self.expires_at, timezone.now()) + duration
        self.renewal_count += 1
        self.save(update_fields=["expires_at", "renewal_count"])

    def recalculate_expiry_for_plan(self, plan):
        max_days = Plan.get(plan, "max_expiry_days")
        if max_days and self.expires_at:
            new_expiry = self.created_at + timedelta(days=max_days)
            if new_expiry > self.expires_at:
                self.expires_at = new_expiry
                self.save(update_fields=["expires_at"])

    def hard_delete(self):
        if self.ns == self.NS_FILE and self.file_public_id:
            try:
                from core.views.b2 import delete_object
                ok = delete_object(self.ns, self.key)
                if not ok:
                    logger.error(
                        "hard_delete: B2 delete failed for %s/%s — DB record preserved",
                        self.ns, self.key,
                    )
            except Exception as e:
                logger.error(
                    "hard_delete: unexpected error deleting B2 object %s/%s: %s",
                    self.ns, self.key, e,
                )
        self.delete()
        return True

    def can_edit(self, user):
        if self.is_creation_locked():
            return False
        if self.owner_id:
            return getattr(user, "is_authenticated", False) and self.owner_id == user.pk
        return True

    def is_creation_locked(self):
        return bool(self.locked_until and timezone.now() < self.locked_until)

    def b2_object_key(self) -> str:
        if self.file_public_id:
            return self.file_public_id
        from core.views.b2 import object_key
        return object_key(self.ns, self.key)

    def download_url(self, expires_in: int = 3600) -> str:
        if self.ns != self.NS_FILE:
            raise ValueError("download_url() called on non-file drop")
        from core.views.b2 import presigned_get
        return presigned_get(self.ns, self.key, filename=self.filename,
                     expires_in=expires_in)


# ── post_delete signal — storage accounting ───────────────────────────────────

@receiver(post_delete, sender=Drop)
def update_storage_on_delete(sender, instance, **kwargs):
    if not instance.owner_id or not instance.filesize:
        return
    try:
        UserProfile.objects.filter(user_id=instance.owner_id).update(
            storage_used_bytes=models.Greatest(
                models.F("storage_used_bytes") - instance.filesize,
                models.Value(0),
            )
        )
    except Exception:
        try:
            profile = UserProfile.objects.get(user_id=instance.owner_id)
            profile.recalc_storage()
        except Exception:
            logger.exception(
                "update_storage_on_delete: failed to update storage for user_id=%s",
                instance.owner_id,
            )


@receiver(post_delete, sender=Drop)
def cleanup_collection_memberships(sender, instance, **kwargs):
    """Remove any CollectionMembership rows pointing at a deleted drop."""
    # Import here to avoid circular reference at module load time
    from core.models import CollectionMembership
    CollectionMembership.objects.filter(ns=instance.ns, key=instance.key).delete()


# ── Collection ────────────────────────────────────────────────────────────────

class Collection(models.Model):
    owner      = models.ForeignKey(User, on_delete=models.CASCADE, related_name="collections")
    slug       = models.SlugField(max_length=60)
    name       = models.CharField(max_length=120)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("owner", "slug")]
        ordering = ["-created_at"]

    def __str__(self):
        return f"@{self.owner.username}/{self.slug}"

    @property
    def url_path(self):
        return f"/@{self.owner.username}/{self.slug}/"

    def can_edit(self, user):
        return getattr(user, "is_authenticated", False) and self.owner_id == user.pk


class CollectionMembership(models.Model):
    collection = models.ForeignKey(Collection, on_delete=models.CASCADE, related_name="memberships")
    ns         = models.CharField(max_length=1, choices=Drop.NS_CHOICES)
    key        = models.CharField(max_length=120)
    added_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("collection", "ns", "key")]
        ordering = ["-added_at"]

    def __str__(self):
        prefix = "f/" if self.ns == Drop.NS_FILE else ""
        return f"{self.collection} → /{prefix}{self.key}/"

    @property
    def drop(self):
        return Drop.objects.filter(ns=self.ns, key=self.key).first()

    @property
    def url_path(self):
        if self.ns == Drop.NS_FILE:
            return f"/f/{self.key}/"
        return f"/{self.key}/"


# ── SavedDrop ─────────────────────────────────────────────────────────────────

class SavedDrop(models.Model):
    user     = models.ForeignKey(User, on_delete=models.CASCADE, related_name="saved_drops")
    ns       = models.CharField(max_length=1, choices=Drop.NS_CHOICES, default=Drop.NS_CLIPBOARD)
    key      = models.CharField(max_length=120)
    saved_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("user", "ns", "key")]
        ordering = ["-saved_at"]

    def __str__(self):
        prefix = "f/" if self.ns == Drop.NS_FILE else ""
        return f"{self.user.email} → /{prefix}{self.key}/"

    @property
    def url_path(self):
        if self.ns == Drop.NS_FILE:
            return f"/f/{self.key}/"
        return f"/{self.key}/"


# ── EmailVerification ─────────────────────────────────────────────────────────

class EmailVerification(models.Model):
    user       = models.OneToOneField(User, on_delete=models.CASCADE, related_name='email_verification')
    token      = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def is_expired(self):
        return (timezone.now() - self.created_at).total_seconds() > 86400  # 24h

    def __str__(self):
        return f'EmailVerification for {self.user.email}'


# ── BugReport ─────────────────────────────────────────────────────────────────

class BugReport(models.Model):
    CATEGORY_CHOICES = [
        ('bug',      'Bug — something is broken'),
        ('ui',       'UI — visual or layout issue'),
        ('perf',     'Performance — it\'s slow'),
        ('feature',  'Feature request'),
        ('security', 'Security concern'),
        ('other',    'Other'),
    ]

    # GitHub label to apply per category
    CATEGORY_LABELS = {
        'bug':      'bug',
        'ui':       'ui',
        'perf':     'performance',
        'feature':  'enhancement',
        'security': 'security',
        'other':    'question',
    }

    user        = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    category    = models.CharField(max_length=16, choices=CATEGORY_CHOICES)
    description = models.TextField()
    hide_identity = models.BooleanField(default=True)
    github_issue_url = models.URLField(blank=True, default='')
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'[{self.category}] by {self.user.email if self.user else "anon"} @ {self.created_at:%Y-%m-%d}'