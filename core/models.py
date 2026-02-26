from django.conf import settings
from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save, pre_delete, post_delete
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
            "max_expiry_days":            None,
            "clipboard_idle_hours":       24,
            "clipboard_max_lifetime_days": 7,
            "anon_file_lifetime_days":    90,
            "storage_gb":                 None,
            "renewals":                   0,
            "password_protection":        False,
            "max_collections":            0,
            "max_groups":                 0,
            "webhooks":                   False,
            "api_keys":                   0,
            "scheduled_drops":            0,
            "helpbot_hourly":             0,
            "smart_parse":                True,
            "api_fetch":                  True,
            "remote_upload":              False,
        },
        FREE: {
            "label":                      "Free",
            "price_monthly":              0,
            "max_file_mb":                200,
            "max_text_kb":                500,
            "max_expiry_days":            None,
            "clipboard_idle_hours":       48,
            "clipboard_max_lifetime_days": 30,
            "anon_file_lifetime_days":    90,
            "storage_gb":                 None,
            "renewals":                   0,
            "password_protection":        False,
            "max_collections":            0,
            "max_groups":                 0,
            "webhooks":                   False,
            "api_keys":                   0,
            "scheduled_drops":            0,
            "helpbot_hourly":             5,
            "smart_parse":                True,
            "api_fetch":                  True,
            "remote_upload":              False,
        },
        STARTER: {
            "label":                      "Starter",
            "price_monthly":              5,
            "max_file_mb":                1024,
            "max_text_kb":                2048,
            "max_expiry_days":            365,
            "clipboard_idle_hours":       None,
            "clipboard_max_lifetime_days": None,
            "anon_file_lifetime_days":    None,
            "storage_gb":                 5,
            "renewals":                   None,
            "password_protection":        True,
            "max_collections":            10,
            "max_groups":                 3,
            "webhooks":                   True,
            "api_keys":                   5,
            "scheduled_drops":            10,
            "helpbot_hourly":             25,
            "smart_parse":                True,
            "api_fetch":                  True,
            "remote_upload":              False,
        },
        PRO: {
            "label":                      "Pro",
            "price_monthly":              10,
            "max_file_mb":                5120,
            "max_text_kb":                10240,
            "max_expiry_days":            365 * 3,
            "clipboard_idle_hours":       None,
            "clipboard_max_lifetime_days": None,
            "anon_file_lifetime_days":    None,
            "storage_gb":                 20,
            "renewals":                   None,
            "password_protection":        True,
            "max_collections":            None,
            "max_groups":                 None,
            "webhooks":                   True,
            "api_keys":                   None,
            "scheduled_drops":            None,
            "helpbot_hourly":             50,
            "smart_parse":                True,
            "api_fetch":                  True,
            "remote_upload":              True,
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
    max_groups                 = models.PositiveIntegerField(null=True, blank=True, default=0,
                                     help_text="null = unlimited, 0 = none")
    webhooks                   = models.BooleanField(default=False)
    api_keys                   = models.PositiveIntegerField(null=True, blank=True, default=0,
                                     help_text="null = unlimited, 0 = none")
    scheduled_drops            = models.PositiveIntegerField(null=True, blank=True, default=0,
                                     help_text="null = unlimited, 0 = none")
    helpbot_hourly             = models.PositiveIntegerField(default=0,
                                     help_text="Help bot questions per hour. 0 = disabled.")
    smart_parse                = models.BooleanField(default=True,
                                     help_text="Allow smart content parsing (--parse, --field).")
    api_fetch                  = models.BooleanField(default=False,
                                     help_text="Allow fetching external URLs via drp get.")
    remote_upload              = models.BooleanField(default=False,
                                     help_text="Allow server-side URL upload (drp up --remote).")

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
            "max_groups":                  self.max_groups,
            "webhooks":                    self.webhooks,
            "api_keys":                    self.api_keys,
            "scheduled_drops":             self.scheduled_drops,
            "helpbot_hourly":              self.helpbot_hourly,
            "smart_parse":                 self.smart_parse,
            "api_fetch":                   self.api_fetch,
            "remote_upload":               self.remote_upload,
        }

    @classmethod
    def _load_cache(cls):
        global _plan_limit_cache
        try:
            loaded = {row.plan: row.as_dict() for row in cls.objects.all()}
            _plan_limit_cache = loaded if loaded else dict(Plan.LIMITS)
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
        (Plan.STARTER, "Starter (CA$5/mo)"),
        (Plan.PRO,     "Pro (CA$10/mo)"),
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
    owner_group = models.ForeignKey(
        "Group", null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="drops",
        help_text="Group that owns this drop (alongside or instead of user owner).",
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

    # ── Scheduled drops ───────────────────────────────────────────────────────
    visible_from = models.DateTimeField(
        null=True, blank=True,
        help_text="Drop is pending/hidden until this time. null = immediately visible.",
    )

    # ── Webhooks (paid) ───────────────────────────────────────────────────────
    webhook_url = models.URLField(
        blank=True, default="",
        help_text="POST to this URL on drop access. Empty = no webhook.",
    )
    notify_before_secs = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Seconds before expiry to send notification. null = no notification.",
    )
    notified_at = models.DateTimeField(
        null=True, blank=True,
        help_text="When the expiry notification was sent. null = not yet sent.",
    )

    # ── Public drops ──────────────────────────────────────────────────────────
    is_public = models.BooleanField(
        default=False, db_index=True,
        help_text="Visible in public feed and searchable.",
    )
    tags = models.CharField(
        max_length=500, blank=True, default="",
        help_text="Comma-separated tags for public discovery. e.g. 'python,snippet'.",
    )

    source_url = models.URLField(
        blank=True, default="",
        help_text="Live API reference. When set, drp get fetches from this URL each time.",
    )

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

    @property
    def is_visible(self):
        """False if the drop is scheduled and the time hasn't come yet."""
        if self.visible_from and timezone.now() < self.visible_from:
            return False
        return True

    def is_expired(self):
        now = timezone.now()

        if self.expires_at:
            return now > self.expires_at

        if self.max_lifetime_secs:
            if (now - self.created_at).total_seconds() > self.max_lifetime_secs:
                return True

        if self.ns == self.NS_CLIPBOARD:
            plan = self.owner_plan if self.owner_id else Plan.ANON
            idle_hours = Plan.get(plan, "clipboard_idle_hours")
            if idle_hours is None:
                return False  # Paid plans: no idle expiry
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
        """Delete from B2 first, then DB.

        Returns False (and preserves DB record) when B2 delete fails,
        so cleanup can retry on the next run.
        The pre_delete signal is a safety net for admin / queryset deletes.
        """
        if self.ns == self.NS_FILE:
            from core.views.b2 import delete_object
            try:
                if not delete_object(self.ns, self.key,
                                     b2_key=self.b2_object_key()):
                    return False
            except Exception:
                logger.error(
                    "hard_delete: B2 error for %s/%s", self.ns, self.key,
                )
                return False
            # Flag so pre_delete signal won't attempt a second B2 call.
            self._b2_cleaned = True
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
                     expires_in=expires_in,
                     b2_key=self.file_public_id or "")


# ── pre_delete signal — B2 object cleanup ─────────────────────────────────────

@receiver(pre_delete, sender=Drop)
def delete_b2_object_on_delete(sender, instance, **kwargs):
    """Remove the file from B2 storage before deleting the DB record.

    Runs on every deletion path: admin, hard_delete(), queryset.delete(), etc.
    """
    if getattr(instance, '_b2_cleaned', False):
        return
    if instance.ns == Drop.NS_FILE:
        try:
            from core.views.b2 import delete_object
            ok = delete_object(instance.ns, instance.key,
                               b2_key=instance.b2_object_key())
            if not ok:
                logger.error(
                    "pre_delete: B2 delete failed for %s/%s (b2_key=%s)",
                    instance.ns, instance.key, instance.b2_object_key(),
                )
        except Exception as e:
            logger.error(
                "pre_delete: unexpected error deleting B2 object %s/%s: %s",
                instance.ns, instance.key, e,
            )


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
    owner_group = models.ForeignKey(
        "Group", null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="collections",
        help_text="Group that owns this collection (alongside or instead of user owner).",
    )
    parent     = models.ForeignKey(
        "self", null=True, blank=True,
        on_delete=models.CASCADE,
        related_name="children",
        help_text="Parent collection for nesting (sub-collections).",
    )
    slug       = models.SlugField(max_length=60)
    name       = models.CharField(max_length=120)
    public_inbox = models.BooleanField(
        default=False,
        help_text="Anyone can drop into this collection; only owner/members can read.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("owner", "parent", "slug")]
        ordering = ["-created_at"]

    def __str__(self):
        return f"@{self.owner.username}/{self.full_path}"

    @property
    def full_path(self):
        """Return the full slash-separated path from root, e.g. 'notes/work'."""
        parts = []
        node = self
        while node is not None:
            parts.append(node.slug)
            node = node.parent
        return '/'.join(reversed(parts))

    @property
    def url_path(self):
        return f"/@{self.owner.username}/{self.full_path}/"

    def can_edit(self, user):
        return getattr(user, "is_authenticated", False) and self.owner_id == user.pk

    def get_ancestors(self):
        """Return list of ancestors from root to self (excluding self)."""
        ancestors = []
        node = self.parent
        while node is not None:
            ancestors.append(node)
            node = node.parent
        return list(reversed(ancestors))

    @classmethod
    def resolve_path(cls, owner, path):
        """Resolve a slash-separated path to a Collection. Returns None if not found."""
        parts = [p for p in path.strip('/').split('/') if p]
        if not parts:
            return None
        parent = None
        collection = None
        for slug in parts:
            collection = cls.objects.filter(owner=owner, parent=parent, slug=slug).first()
            if collection is None:
                return None
            parent = collection
        return collection


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
        ('security', 'Security concern'),
        ('other',    'Other'),
    ]

    # GitHub label to apply per category
    CATEGORY_LABELS = {
        'bug':      'bug',
        'ui':       'ui',
        'perf':     'performance',
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


# ── Group ────────────────────────────────────────────────────────────────────────

class Group(models.Model):
    """A named group that can own drops and collections."""
    handle     = models.CharField(max_length=60, unique=True, db_index=True,
                                  help_text="Unique @handle for the group.")
    name       = models.CharField(max_length=120)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True,
                                   related_name="created_groups")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"@{self.handle}"


class GroupMembership(models.Model):
    ROLE_READER = "reader"
    ROLE_WRITER = "writer"
    ROLE_ADMIN  = "admin"
    ROLE_CHOICES = [
        (ROLE_READER, "Reader"),
        (ROLE_WRITER, "Writer"),
        (ROLE_ADMIN,  "Admin"),
    ]

    group    = models.ForeignKey(Group, on_delete=models.CASCADE, related_name="memberships")
    user     = models.ForeignKey(User, on_delete=models.CASCADE, related_name="group_memberships")
    role     = models.CharField(max_length=8, choices=ROLE_CHOICES, default=ROLE_READER)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("group", "user")]
        ordering = ["role", "joined_at"]

    def __str__(self):
        return f"{self.user.username} → @{self.group.handle} [{self.role}]"


class GroupInviteToken(models.Model):
    """A single-use or limited-use invite token for joining a group."""
    group      = models.ForeignKey(Group, on_delete=models.CASCADE, related_name="invite_tokens")
    token      = models.CharField(max_length=64, unique=True, db_index=True)
    role       = models.CharField(max_length=8, choices=GroupMembership.ROLE_CHOICES,
                                  default=GroupMembership.ROLE_READER)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    max_uses   = models.PositiveIntegerField(null=True, blank=True,
                                             help_text="null = unlimited, 1 = single-use")
    use_count  = models.PositiveIntegerField(default=0)

    def is_expired(self):
        if self.expires_at and timezone.now() > self.expires_at:
            return True
        if self.max_uses is not None and self.use_count >= self.max_uses:
            return True
        return False

    def __str__(self):
        return f"Invite to @{self.group.handle} [{self.role}]"


# ── APIToken (paid) ─────────────────────────────────────────────────────────────

class APIToken(models.Model):
    """Static API token for CI/scripts. Paid accounts only."""
    user       = models.ForeignKey(User, on_delete=models.CASCADE, related_name="api_tokens")
    token_hash = models.CharField(max_length=256, unique=True,
                                  help_text="SHA-256 hash of the token. Never store plaintext.")
    prefix     = models.CharField(max_length=8, db_index=True,
                                  help_text="First 8 chars of the token for identification.")
    label      = models.CharField(max_length=120, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    last_used  = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def is_expired(self):
        return self.expires_at is not None and timezone.now() > self.expires_at

    def __str__(self):
        return f"APIToken {self.prefix}... ({self.user.username})"


# ── Alias ────────────────────────────────────────────────────────────────────────

class Alias(models.Model):
    """Server-side alias: /@handle/alias → a drop key."""
    owner      = models.ForeignKey(User, on_delete=models.CASCADE, related_name="aliases")
    alias      = models.CharField(max_length=120)
    ns         = models.CharField(max_length=1, choices=Drop.NS_CHOICES, default=Drop.NS_CLIPBOARD)
    key        = models.CharField(max_length=120, help_text="Drop key this alias points to.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("owner", "alias")]
        ordering = ["-created_at"]

    def __str__(self):
        return f"@{self.owner.username}/{self.alias} → /{self.key}/"


# ── DropTemplate ──────────────────────────────────────────────────────────────────

class DropTemplate(models.Model):
    """Reusable drop template. User or group owned."""
    owner       = models.ForeignKey(User, null=True, blank=True,
                                    on_delete=models.CASCADE, related_name="drop_templates")
    owner_group = models.ForeignKey(Group, null=True, blank=True,
                                    on_delete=models.CASCADE, related_name="drop_templates")
    slug        = models.SlugField(max_length=60)
    name        = models.CharField(max_length=120)
    content     = models.TextField(blank=True, default="",
                                   help_text="Default content for clipboard drops.")
    burn        = models.BooleanField(default=False)
    expiry_days = models.PositiveIntegerField(null=True, blank=True)
    password    = models.BooleanField(default=False,
                                      help_text="Prompt for password when using this template.")
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        owner = self.owner.username if self.owner else (f"@{self.owner_group.handle}" if self.owner_group else "?")
        return f"{owner}/{self.slug}"


# ── FeatureProposal + FeatureVote ────────────────────────────────────────────────

class FeatureProposal(models.Model):
    title       = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    proposed_by = models.ForeignKey(User, null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="feature_proposals")
    staff_pick  = models.BooleanField(default=False, help_text="Weekly staff highlight")
    created_at  = models.DateTimeField(auto_now_add=True)
    closed      = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]

    def total_weight(self):
        return self.votes.aggregate(total=models.Sum("weight"))["total"] or 0

    def __str__(self):
        return self.title


class FeatureVote(models.Model):
    """One vote per user per proposal. Weight: free=1, paid=3."""
    proposal   = models.ForeignKey(FeatureProposal, on_delete=models.CASCADE, related_name="votes")
    user       = models.ForeignKey(User, on_delete=models.CASCADE, related_name="feature_votes")
    weight     = models.PositiveSmallIntegerField(default=1,
                                                  help_text="free=1, paid=3")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("proposal", "user")]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user.username} voted on '{self.proposal.title}' (w={self.weight})"


# ── TransferToken ─────────────────────────────────────────────────────────────

class TransferToken(models.Model):
    """One-time token to transfer drop ownership. Expires after 24 h."""
    drop       = models.ForeignKey(Drop, on_delete=models.CASCADE, related_name="transfer_tokens")
    token      = models.CharField(max_length=64, unique=True, db_index=True)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name="transfer_tokens_sent")
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    claimed_by = models.ForeignKey(User, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="transfer_tokens_claimed")
    claimed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def is_valid(self):
        return self.claimed_by is None and timezone.now() < self.expires_at

    def __str__(self):
        status = "claimed" if self.claimed_by else ("expired" if not self.is_valid() else "pending")
        return f"Transfer {self.drop} [{status}]"


# ── DropLike ──────────────────────────────────────────────────────────────────

class DropLike(models.Model):
    """One like per user per drop. Only public drops can be liked."""
    drop       = models.ForeignKey(Drop, on_delete=models.CASCADE, related_name="likes")
    user       = models.ForeignKey(User, on_delete=models.CASCADE, related_name="drop_likes")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("drop", "user")]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user.username} liked {self.drop}"


# ── Help Bot History ──────────────────────────────────────────────────────────

class EmailTemplate(models.Model):
    """
    Admin-editable email templates stored in DB.
    Each template is identified by a unique slug (e.g. 'verify_email').
    The subject/body support Python .format() placeholders.
    """
    slug        = models.SlugField(max_length=80, unique=True, help_text="Unique identifier, e.g. verify_email")
    description = models.CharField(max_length=200, blank=True, help_text="Admin note about where this template is used")
    subject     = models.CharField(max_length=200)
    body_text   = models.TextField(help_text="Plain text body. Use {placeholder} for variables.")
    body_html   = models.TextField(blank=True, help_text="Optional HTML body. Leave blank for plain-text-only emails.")
    from_email  = models.EmailField(blank=True, help_text="Override from address. Blank = DEFAULT_FROM_EMAIL.")
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['slug']

    def __str__(self):
        return self.slug

    @classmethod
    def get(cls, slug):
        """Return the template for *slug*, or None if not in DB yet."""
        try:
            return cls.objects.get(slug=slug)
        except cls.DoesNotExist:
            return None

    def render_subject(self, **kwargs):
        return self.subject.format(**kwargs)

    def render_text(self, **kwargs):
        return self.body_text.format(**kwargs)

    def render_html(self, **kwargs):
        if not self.body_html:
            return ''
        return self.body_html.format(**kwargs)

    def get_from_email(self):
        return self.from_email or settings.DEFAULT_FROM_EMAIL


# ── Help Bot History ──────────────────────────────────────────────────────────

class HelpBotHistory(models.Model):
    """Server-side storage for help bot conversations, synced across CLI and web."""

    user       = models.OneToOneField(User, on_delete=models.CASCADE, related_name="helpbot_history")
    messages   = models.JSONField(default=list, help_text="List of {q, a} dicts")
    updated_at = models.DateTimeField(auto_now=True)

    MAX_MESSAGES = 20

    class Meta:
        verbose_name_plural = "help bot histories"

    def __str__(self):
        return f"{self.user.username} helpbot ({len(self.messages)} messages)"

    def append(self, question: str, answer_html: str):
        self.messages.append({"q": question, "a": answer_html})
        self.messages = self.messages[-self.MAX_MESSAGES:]
        self.save(update_fields=["messages", "updated_at"])

    def clear(self):
        self.messages = []
        self.save(update_fields=["messages", "updated_at"])