"""Tests for plan limits enforcement on drive operations.

These tests verify that plan-gated features are correctly enforced:
- Anonymous: no custom keys, no passwords, 1-day max expiry, 200 MB file limit
- Free:      custom keys, no passwords, 7-day max expiry, 200 MB file limit
- Starter:   custom keys, passwords, 365-day max expiry, 1 GB file limit
- Pro:       custom keys, passwords, 3-year max expiry, 5 GB file limit, path access
"""

import pytest
from datetime import timedelta

from django.contrib.auth.models import User
from django.utils import timezone

from core.models import ANONYMOUS_LIMITS, Plan, PlanLimits, UserProfile, plan_display
from drive.models import File, Folder, Key


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def anon_user(db):
    u = User.objects.create_user(username="anon_abc", password="pass")
    UserProfile.objects.create(user=u, is_anonymous=True)
    return u


@pytest.fixture
def free_user(db):
    u = User.objects.create_user(username="freeuser", password="pass")
    UserProfile.objects.create(user=u, plan=Plan.FREE)
    return u


@pytest.fixture
def starter_user(db):
    u = User.objects.create_user(username="starter", password="pass")
    UserProfile.objects.create(user=u, plan=Plan.STARTER)
    return u


@pytest.fixture
def pro_user(db):
    u = User.objects.create_user(username="pro", password="pass")
    UserProfile.objects.create(user=u, plan=Plan.PRO)
    return u


def _make_file(user, filesize=100, folder=None):
    return File.objects.create(
        owner=user, folder=folder, filename=f"f_{filesize}.bin",
        content_type="application/octet-stream", filesize=filesize,
        b2_key=f"uuid/{filesize}",
    )


def _make_key(file, **kwargs):
    from drive.models import _generate_key
    return Key.objects.create(key=_generate_key(), file=file, **kwargs)


# ── Anonymous limits ─────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestAnonymousLimits:
    def test_no_custom_keys(self):
        assert ANONYMOUS_LIMITS["custom_keys"] is False

    def test_no_passwords(self):
        assert ANONYMOUS_LIMITS["password_protected"] is False

    def test_max_expiry_1_day(self):
        assert ANONYMOUS_LIMITS["max_expiry_days"] == 1

    def test_max_file_200mb(self):
        assert ANONYMOUS_LIMITS["max_file_bytes"] == 200 * 1024**2

    def test_no_storage(self):
        assert ANONYMOUS_LIMITS["storage_bytes"] == 0

    def test_plan_display_anonymous(self):
        d = plan_display("anonymous")
        assert d["plan"] == "anonymous"
        assert d["max_file_mb"] == 200
        assert d["expiry_display"] == "1 day"
        assert d["custom_keys"] is False


# ── Free plan limits ─────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestFreeLimits:
    def test_custom_keys_allowed(self, free_user):
        limits = free_user.profile.limits
        assert limits["custom_keys"] is True

    def test_no_passwords(self, free_user):
        limits = free_user.profile.limits
        assert limits["password_protected"] is False

    def test_max_expiry_7_days(self, free_user):
        limits = free_user.profile.limits
        assert limits["max_expiry_days"] == 7

    def test_max_file_200mb(self, free_user):
        limits = free_user.profile.limits
        assert limits["max_file_bytes"] == 200 * 1024**2

    def test_storage_1gb(self, free_user):
        limits = free_user.profile.limits
        assert limits["storage_bytes"] == 1 * 1024**3

    def test_helpbot_5_per_hr(self, free_user):
        limits = free_user.profile.limits
        assert limits["helpbot_calls_per_hr"] == 5


# ── Starter plan limits ─────────────────────────────────────────────────────

@pytest.mark.django_db
class TestStarterLimits:
    def test_passwords_allowed(self, starter_user):
        limits = starter_user.profile.limits
        assert limits["password_protected"] is True

    def test_max_expiry_365_days(self, starter_user):
        limits = starter_user.profile.limits
        assert limits["max_expiry_days"] == 365

    def test_max_file_1gb(self, starter_user):
        limits = starter_user.profile.limits
        assert limits["max_file_bytes"] == 1 * 1024**3

    def test_storage_5gb(self, starter_user):
        limits = starter_user.profile.limits
        assert limits["storage_bytes"] == 5 * 1024**3

    def test_helpbot_30_per_hr(self, starter_user):
        limits = starter_user.profile.limits
        assert limits["helpbot_calls_per_hr"] == 30


# ── Pro plan limits ──────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestProLimits:
    def test_passwords_allowed(self, pro_user):
        limits = pro_user.profile.limits
        assert limits["password_protected"] is True

    def test_max_expiry_3_years(self, pro_user):
        limits = pro_user.profile.limits
        assert limits["max_expiry_days"] == 365 * 3

    def test_max_file_5gb(self, pro_user):
        limits = pro_user.profile.limits
        assert limits["max_file_bytes"] == 5 * 1024**3

    def test_storage_20gb(self, pro_user):
        limits = pro_user.profile.limits
        assert limits["storage_bytes"] == 20 * 1024**3

    def test_helpbot_120_per_hr(self, pro_user):
        limits = pro_user.profile.limits
        assert limits["helpbot_calls_per_hr"] == 120


# ── Path access is Pro-only ─────────────────────────────────────────────────

@pytest.mark.django_db
class TestPathAccess:
    def test_folder_path_access_default_off(self, free_user):
        f = Folder.objects.create(owner=free_user, name="x", slug="x")
        assert not f.path_access_allowed()

    def test_pro_can_enable_path_access(self, pro_user):
        f = Folder.objects.create(
            owner=pro_user, name="public", slug="public", path_public=True,
        )
        assert f.path_access_allowed()

    def test_child_inherits_path_access(self, pro_user):
        parent = Folder.objects.create(
            owner=pro_user, name="root", slug="root", path_public=True,
        )
        child = Folder.objects.create(
            owner=pro_user, name="sub", slug="sub", parent=parent,
        )
        assert child.path_access_allowed()

    def test_child_can_override_disabled_parent(self, pro_user):
        """A child can re-enable path access even if parent is off."""
        parent = Folder.objects.create(
            owner=pro_user, name="root", slug="root", path_public=False,
        )
        child = Folder.objects.create(
            owner=pro_user, name="open", slug="open",
            parent=parent, path_public=True,
        )
        assert not parent.path_access_allowed()
        assert child.path_access_allowed()


# ── Plan limits DB override ─────────────────────────────────────────────────

@pytest.mark.django_db
class TestPlanLimitsOverride:
    """Verify that DB-stored PlanLimits override hardcoded defaults."""

    def test_db_limits_take_precedence(self, free_user):
        PlanLimits.objects.update_or_create(
            plan=Plan.FREE,
            defaults=dict(
                storage_bytes=2 * 1024**3,
                max_file_bytes=500 * 1024**2,
                max_expiry_days=14,
                password_protected=True,
                custom_keys=True,
                helpbot_calls_per_hr=10,
            ),
        )
        limits = free_user.profile.limits
        assert limits["storage_bytes"] == 2 * 1024**3
        assert limits["max_file_bytes"] == 500 * 1024**2
        assert limits["max_expiry_days"] == 14
        assert limits["password_protected"] is True
        assert limits["helpbot_calls_per_hr"] == 10


# ── Storage tracking ────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestStorageTracking:
    def test_storage_used_default_zero(self, free_user):
        assert free_user.profile.storage_used == 0

    def test_storage_used_gb(self, free_user):
        free_user.profile.storage_used = 1024**3
        assert free_user.profile.storage_used_gb == 1.0

    def test_is_paid_free(self, free_user):
        assert not free_user.profile.is_paid

    def test_is_paid_starter(self, starter_user):
        assert starter_user.profile.is_paid

    def test_is_paid_pro(self, pro_user):
        assert pro_user.profile.is_paid


# ── Key expiry enforcement (model-level) ─────────────────────────────────────

@pytest.mark.django_db
class TestKeyExpiry:
    def test_key_within_plan_max(self, free_user):
        """Key with expiry within plan max is valid."""
        f = _make_file(free_user)
        k = _make_key(f, expires_at=timezone.now() + timedelta(days=5))
        assert k.is_valid

    def test_expired_key_is_invalid(self, free_user):
        """Key past expiry is invalid."""
        f = _make_file(free_user)
        k = _make_key(f, expires_at=timezone.now() - timedelta(seconds=1))
        assert not k.is_valid

    def test_burn_key_valid_before_view(self, free_user):
        f = _make_file(free_user)
        k = _make_key(f, burn=True)
        assert k.is_valid

    def test_burn_key_invalid_after_view(self, free_user):
        f = _make_file(free_user)
        k = _make_key(f, burn=True)
        k.mark_burned()
        k.refresh_from_db()
        assert not k.is_valid


# ── plan_display helper ──────────────────────────────────────────────────────

@pytest.mark.django_db
class TestPlanDisplay:
    def test_free_display(self):
        d = plan_display(Plan.FREE)
        assert d["label"] == "Free"
        assert d["max_file_mb"] == 200
        assert d["storage_gb"] == 1
        assert d["expiry_display"] == "7 days"

    def test_starter_display(self):
        d = plan_display(Plan.STARTER)
        assert d["label"] == "Starter"
        assert d["expiry_display"] == "1 year"

    def test_pro_display(self):
        d = plan_display(Plan.PRO)
        assert d["label"] == "Pro"
        assert d["expiry_display"] == "3 years"
        assert d["storage_gb"] == 20
