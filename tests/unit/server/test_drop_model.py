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


def _drop(owner=None, key='test', **kw):
    """Create a drop with sensible defaults."""
    return Drop.objects.create(owner=owner, key=key, **kw)


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
        d = _drop(key='file1', file_public_id='drops/file1')
        Drop.objects.filter(pk=d.pk).update(
            created_at=timezone.now() - timedelta(days=91))
        d.refresh_from_db()
        assert d.is_expired()

    def test_file_drop_not_expired_under_90_days(self):
        d = _drop(key='file2', file_public_id='drops/file2')
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


# ── Computed kind / is_file / is_text ─────────────────────────────────────────

class TestComputedKind:
    def test_text_drop_kind(self):
        d = _drop(key='ck1', content='hello')
        assert d.kind == 'text'
        assert d.is_text is True
        assert d.is_file is False

    def test_file_drop_kind(self):
        d = _drop(key='ck2', file_public_id='drops/ck2')
        assert d.kind == 'file'
        assert d.is_file is True
        assert d.is_text is False


# ── content_format detection ──────────────────────────────────────────────────

class TestContentFormat:
    # ── text drops ────────────────────────────────────────────────────────
    def test_empty_text(self):
        d = _drop(key='cf1', content='')
        assert d.content_format == 'text'

    def test_plain_text(self):
        d = _drop(key='cf2', content='just some words')
        assert d.content_format == 'text'

    def test_json_object(self):
        d = _drop(key='cf3', content='{"key": "value"}')
        assert d.content_format == 'json'

    def test_json_array(self):
        d = _drop(key='cf4', content='[1, 2, 3]')
        assert d.content_format == 'json'

    def test_csv(self):
        d = _drop(key='cf5', content='a,b,c\n1,2,3\n4,5,6')
        assert d.content_format == 'csv'

    def test_xml(self):
        d = _drop(key='cf6', content='<?xml version="1.0"?><root/>')
        assert d.content_format == 'xml'

    def test_yaml(self):
        d = _drop(key='cf7', content='---\nkey: value\n')
        assert d.content_format == 'yaml'

    def test_markdown(self):
        d = _drop(key='cf8', content='# Title\nsome text')
        assert d.content_format == 'markdown'

    def test_python(self):
        d = _drop(key='cf9', content='import os\nprint(os.getcwd())')
        assert d.content_format == 'python'

    def test_shell(self):
        d = _drop(key='cf10', content='#!/bin/bash\necho hello')
        assert d.content_format == 'shell'

    def test_sql(self):
        d = _drop(key='cf11', content='SELECT * FROM users')
        assert d.content_format == 'sql'

    def test_html(self):
        d = _drop(key='cf12', content='<!DOCTYPE html><html></html>')
        assert d.content_format == 'html'

    # ── file drops ────────────────────────────────────────────────────────
    def test_file_by_extension(self):
        d = _drop(key='cf20', file_public_id='drops/cf20', filename='data.csv')
        assert d.content_format == 'csv'

    def test_file_python(self):
        d = _drop(key='cf21', file_public_id='drops/cf21', filename='main.py')
        assert d.content_format == 'python'

    def test_file_archive(self):
        d = _drop(key='cf22', file_public_id='drops/cf22', filename='pkg.tar.gz')
        assert d.content_format == 'archive'

    def test_file_image_by_mime(self):
        d = _drop(key='cf23', file_public_id='drops/cf23',
                  content_type='image/png')
        assert d.content_format == 'image'

    def test_file_json_by_mime(self):
        d = _drop(key='cf24', file_public_id='drops/cf24',
                  content_type='application/json')
        assert d.content_format == 'json'

    def test_file_unknown_binary(self):
        d = _drop(key='cf25', file_public_id='drops/cf25')
        assert d.content_format == 'binary'

    def test_file_pdf(self):
        d = _drop(key='cf26', file_public_id='drops/cf26', filename='report.pdf')
        assert d.content_format == 'pdf'
