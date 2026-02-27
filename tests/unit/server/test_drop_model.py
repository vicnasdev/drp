"""
Tests for core.models.Drop — expiry, touch, password, can_edit, renew.

Uses pytest-django markers for DB access.
"""

import pytest
from datetime import timedelta
from django.utils import timezone
from django.contrib.auth.models import User

from core.models import Drop, Plan, UserProfile

pytestmark = pytest.mark.django_db


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def user(db):
    return User.objects.create_user('alice', 'alice@test.com', 'pw')


@pytest.fixture
def other_user(db):
    return User.objects.create_user('bob', 'bob@test.com', 'pw')


def _drop(owner=None, kind='text', key='test', **kw):
    """Create a drop with sensible defaults."""
    return Drop.objects.create(owner=owner, kind=kind, key=key, **kw)


# ── Expiry ────────────────────────────────────────────────────────────────────

class TestDropExpiry:
    def test_explicit_expires_at_past(self, user):
        d = _drop(owner=user, expires_at=timezone.now() - timedelta(hours=1))
        assert d.is_expired()

    def test_explicit_expires_at_future(self, user):
        d = _drop(owner=user, key='f1',
                  expires_at=timezone.now() + timedelta(days=30))
        assert not d.is_expired()

    def test_anon_clipboard_idle_24h(self):
        d = _drop(key='anon1',
                  last_accessed_at=timezone.now() - timedelta(hours=25))
        assert d.is_expired()

    def test_anon_clipboard_not_expired_under_24h(self):
        d = _drop(key='anon2',
                  last_accessed_at=timezone.now() - timedelta(hours=1))
        assert not d.is_expired()

    def test_file_drop_expires_after_90_days(self):
        d = _drop(key='file1', kind='file')
        Drop.objects.filter(pk=d.pk).update(
            created_at=timezone.now() - timedelta(days=91))
        d.refresh_from_db()
        assert d.is_expired()

    def test_file_drop_not_expired_under_90_days(self):
        d = _drop(key='file2', kind='file')
        assert not d.is_expired()

    def test_paid_clipboard_never_idle_expires(self, user):
        UserProfile.objects.filter(user=user).update(plan=Plan.STARTER)
        # Re-fetch user to clear cached profile relation
        fresh = User.objects.get(pk=user.pk)
        d = _drop(owner=fresh, key='paid1',
                  last_accessed_at=timezone.now() - timedelta(days=365))
        assert not d.is_expired()


# ── Password ──────────────────────────────────────────────────────────────────

class TestDropPassword:
    def test_no_password_by_default(self, user):
        d = _drop(owner=user, key='pw1')
        assert not d.is_password_protected

    def test_set_password_marks_protected(self, user):
        d = _drop(owner=user, key='pw2')
        d.set_password('secret')
        assert d.is_password_protected

    def test_correct_password_accepted(self, user):
        d = _drop(owner=user, key='pw3')
        d.set_password('secret')
        assert d.check_password('secret')

    def test_wrong_password_rejected(self, user):
        d = _drop(owner=user, key='pw4')
        d.set_password('secret')
        assert not d.check_password('wrong')

    def test_clear_password(self, user):
        d = _drop(owner=user, key='pw5')
        d.set_password('secret')
        d.set_password(None)
        assert not d.is_password_protected


# ── can_edit ──────────────────────────────────────────────────────────────────

class TestCanEdit:
    def test_anon_drop_editable_by_anyone(self, user):
        d = _drop(key='ce1')
        assert d.can_edit(user)

    def test_owned_drop_editable_by_owner(self, user):
        d = _drop(owner=user, key='ce2')
        assert d.can_edit(user)

    def test_owned_drop_not_editable_by_other(self, user, other_user):
        d = _drop(owner=user, key='ce3')
        assert not d.can_edit(other_user)

    def test_creation_locked_drop_not_editable(self, user):
        d = _drop(owner=user, key='ce4',
                  locked_until=timezone.now() + timedelta(hours=1))
        assert not d.can_edit(user)

    def test_expired_lock_allows_edit(self, user):
        d = _drop(owner=user, key='ce5',
                  locked_until=timezone.now() - timedelta(hours=1))
        assert d.can_edit(user)


# ── Renew ─────────────────────────────────────────────────────────────────────

class TestDropRenew:
    def test_renew_pushes_expiry_forward(self, user):
        original = timezone.now() + timedelta(days=7)
        d = _drop(owner=user, key='rn1', expires_at=original)
        d.renew()
        d.refresh_from_db()
        assert d.expires_at > original
        assert d.renewal_count == 1

    def test_renew_no_op_without_expiry(self, user):
        d = _drop(owner=user, key='rn2')
        d.renew()
        d.refresh_from_db()
        assert d.expires_at is None
        assert d.renewal_count == 0


# ── Touch ─────────────────────────────────────────────────────────────────────

class TestDropTouch:
    def test_touch_sets_accessed_when_never_touched(self, user):
        d = _drop(owner=user, key='t1')
        assert d.last_accessed_at is None
        d.touch()
        assert d.last_accessed_at is not None

    def test_touch_skips_within_debounce(self, user):
        d = _drop(owner=user, key='t2')
        d.touch()
        first = d.last_accessed_at
        d.touch()  # should be skipped
        assert d.last_accessed_at == first

    def test_touch_increments_view_count(self, user):
        d = _drop(owner=user, key='t3')
        d.touch()
        d.refresh_from_db()
        assert d.view_count == 1

    def test_touch_updates_after_debounce(self, user):
        d = _drop(owner=user, key='t4')
        d.touch()
        # Manually push last_accessed to past
        past = timezone.now() - timedelta(seconds=Drop.TOUCH_DEBOUNCE_SECS + 1)
        Drop.objects.filter(pk=d.pk).update(last_accessed_at=past)
        d.refresh_from_db()
        d.touch()
        d.refresh_from_db()
        assert d.view_count == 2
