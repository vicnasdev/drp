"""
tests/unit/test_drop_model.py

Unit tests for Drop model methods: is_expired(), touch(), hard_delete(),
password helpers, can_edit(), renew(), recalculate_expiry_for_plan().
Uses Django TestCase with a SQLite test DB — no network.
"""

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from core.models import Drop, Plan, UserProfile


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_user(username="u", plan=Plan.FREE):
    u = User.objects.create_user(username, password="pw")
    UserProfile.objects.filter(user=u).update(plan=plan)
    u.refresh_from_db()
    return u


def _make_drop(ns=Drop.NS_CLIPBOARD, key="x", kind=Drop.TEXT, owner=None, **kwargs):
    defaults = dict(ns=ns, key=key, kind=kind, owner=owner)
    defaults.update(kwargs)
    return Drop(**defaults)


def _make_db_drop(ns=Drop.NS_CLIPBOARD, key="x", kind=Drop.TEXT, owner=None, **kwargs):
    defaults = dict(ns=ns, key=key, kind=kind, owner=owner)
    defaults.update(kwargs)
    return Drop.objects.create(**defaults)


def _make_file_drop(key="file", owner=None, filesize=1000, **kwargs):
    return Drop.objects.create(
        ns=Drop.NS_FILE, key=key, kind=Drop.FILE,
        file_public_id=f"drops/f/{key}", filename=f"{key}.bin",
        filesize=filesize, owner=owner, **kwargs,
    )


# ── Drop.is_expired() ─────────────────────────────────────────────────────────

class TestDropExpiry(TestCase):
    def test_explicit_expires_at_past(self):
        d = _make_drop(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertTrue(d.is_expired())

    def test_explicit_expires_at_future(self):
        d = _make_drop(expires_at=timezone.now() + timedelta(days=1))
        self.assertFalse(d.is_expired())

    def test_max_lifetime_exceeded(self):
        d = _make_drop(max_lifetime_secs=50)
        d.created_at = timezone.now() - timedelta(seconds=100)
        self.assertTrue(d.is_expired())

    def test_max_lifetime_not_exceeded(self):
        d = _make_drop(max_lifetime_secs=200)
        d.created_at = timezone.now() - timedelta(seconds=100)
        self.assertFalse(d.is_expired())

    def test_anon_clipboard_idle_24h(self):
        d = _make_drop(owner=None, last_accessed_at=timezone.now() - timedelta(hours=25))
        d.created_at = timezone.now() - timedelta(hours=25)
        self.assertTrue(d.is_expired())

    def test_anon_clipboard_not_expired_under_24h(self):
        d = _make_drop(owner=None, last_accessed_at=timezone.now() - timedelta(hours=23))
        d.created_at = timezone.now() - timedelta(hours=23)
        self.assertFalse(d.is_expired())

    def test_file_drop_expires_after_90_days(self):
        d = _make_drop(ns=Drop.NS_FILE, kind=Drop.FILE)
        d.created_at = timezone.now() - timedelta(days=91)
        self.assertTrue(d.is_expired())

    def test_file_drop_not_expired_under_90_days(self):
        d = _make_drop(ns=Drop.NS_FILE, kind=Drop.FILE)
        d.created_at = timezone.now() - timedelta(days=89)
        self.assertFalse(d.is_expired())


# ── Drop.touch() debounce ─────────────────────────────────────────────────────

class TestDropTouch(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("touch_user", password="pw")
        self.drop = _make_db_drop(key="touch-test", owner=self.user)

    def test_touch_sets_accessed_when_never_touched(self):
        self.assertIsNone(self.drop.last_accessed_at)
        self.drop.touch()
        self.drop.refresh_from_db()
        self.assertIsNotNone(self.drop.last_accessed_at)

    def test_touch_skips_within_debounce(self):
        recent = timezone.now() - timedelta(seconds=60)
        Drop.objects.filter(pk=self.drop.pk).update(last_accessed_at=recent)
        self.drop.last_accessed_at = recent
        self.drop.touch()
        self.drop.refresh_from_db()
        self.assertAlmostEqual(
            self.drop.last_accessed_at.timestamp(), recent.timestamp(), delta=2
        )

    def test_touch_updates_after_debounce(self):
        old = timezone.now() - timedelta(seconds=Drop.TOUCH_DEBOUNCE_SECS + 10)
        Drop.objects.filter(pk=self.drop.pk).update(last_accessed_at=old)
        self.drop.last_accessed_at = old
        self.drop.touch()
        self.drop.refresh_from_db()
        self.assertGreater(self.drop.last_accessed_at, old)

    def test_touch_increments_view_count(self):
        self.drop.touch()
        self.drop.refresh_from_db()
        self.assertEqual(self.drop.view_count, 1)


# ── Drop.hard_delete() ────────────────────────────────────────────────────────

class TestHardDelete(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("hd_user", password="pw")

    def test_file_drop_calls_b2_delete(self):
        drop = _make_file_drop(key="del-file", owner=self.user, filesize=1000)
        UserProfile.objects.filter(user=self.user).update(storage_used_bytes=1000)
        with patch("core.views.b2.delete_object") as mock_del:
            drop.hard_delete()
            mock_del.assert_called_once_with(Drop.NS_FILE, "del-file")

    def test_text_drop_no_b2_call(self):
        drop = _make_db_drop(key="del-text", owner=self.user)
        with patch("core.views.b2.delete_object") as mock_del:
            drop.hard_delete()
            mock_del.assert_not_called()

    def test_b2_error_preserves_db_record_for_retry(self):
        """When B2 delete fails, hard_delete returns False and keeps DB row."""
        drop = _make_file_drop(key="b2-err")
        pk = drop.pk
        with patch("core.views.b2.delete_object", side_effect=Exception("network")):
            result = drop.hard_delete()
        self.assertFalse(result)
        self.assertTrue(Drop.objects.filter(pk=pk).exists())

    def test_storage_decremented_on_delete(self):
        drop = _make_file_drop(key="size-del", owner=self.user, filesize=2048)
        UserProfile.objects.filter(user=self.user).update(storage_used_bytes=2048)
        with patch("core.views.b2.delete_object"):
            drop.hard_delete()
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.storage_used_bytes, 0)

    def test_anon_drop_delete_does_not_crash(self):
        drop = _make_file_drop(key="anon-del", owner=None, filesize=500)
        with patch("core.views.b2.delete_object"):
            drop.hard_delete()
        self.assertFalse(Drop.objects.filter(key="anon-del").exists())

    def test_plain_delete_also_removes_b2(self):
        """Admin / ORM .delete() triggers B2 cleanup via pre_delete signal."""
        drop = _make_file_drop(key="admin-del", owner=self.user, filesize=512)
        with patch("core.views.b2.delete_object") as mock_del:
            drop.delete()
            mock_del.assert_called_once_with(Drop.NS_FILE, "admin-del")
        self.assertFalse(Drop.objects.filter(key="admin-del").exists())


# ── Drop password helpers ─────────────────────────────────────────────────────

class TestDropPassword(TestCase):
    def setUp(self):
        self.drop = _make_db_drop(key="pw-drop")

    def test_no_password_by_default(self):
        self.assertFalse(self.drop.is_password_protected)

    def test_set_password_marks_protected(self):
        self.drop.set_password("secret")
        self.drop.save()
        self.assertTrue(self.drop.is_password_protected)

    def test_correct_password_accepted(self):
        self.drop.set_password("secret")
        self.drop.save()
        self.assertTrue(self.drop.check_password("secret"))

    def test_wrong_password_rejected(self):
        self.drop.set_password("secret")
        self.drop.save()
        self.assertFalse(self.drop.check_password("wrong"))

    def test_clear_password(self):
        self.drop.set_password("secret")
        self.drop.save()
        self.drop.set_password(None)
        self.drop.save()
        self.assertFalse(self.drop.is_password_protected)


# ── Drop.can_edit() ───────────────────────────────────────────────────────────

class TestCanEdit(TestCase):
    def setUp(self):
        self.owner  = User.objects.create_user("owner_ce", password="pw")
        self.other  = User.objects.create_user("other_ce", password="pw")

    def test_anon_drop_editable_by_anyone(self):
        drop = _make_db_drop(key="open", owner=None)
        from unittest.mock import MagicMock
        anon = MagicMock(is_authenticated=False)
        self.assertTrue(drop.can_edit(anon))

    def test_owned_drop_editable_by_owner(self):
        drop = _make_db_drop(key="owned-ok", owner=self.owner)
        self.assertTrue(drop.can_edit(self.owner))

    def test_owned_drop_not_editable_by_other(self):
        drop = _make_db_drop(key="owned-no", owner=self.owner)
        self.assertFalse(drop.can_edit(self.other))

    def test_creation_locked_drop_not_editable_by_anyone(self):
        locked_until = timezone.now() + timedelta(hours=12)
        drop = _make_db_drop(key="locked-new", owner=None, locked_until=locked_until)
        self.assertFalse(drop.can_edit(self.owner))


# ── Drop.renew() ──────────────────────────────────────────────────────────────

class TestDropRenew(TestCase):
    def test_renew_pushes_expiry_forward(self):
        drop = _make_db_drop(
            key="renew-ok",
            expires_at=timezone.now() + timedelta(days=7),
        )
        original = drop.expires_at
        drop.renew()
        drop.refresh_from_db()
        self.assertGreater(drop.expires_at, original)
        self.assertEqual(drop.renewal_count, 1)

    def test_renew_no_op_without_expiry(self):
        drop = _make_db_drop(key="renew-noop")
        drop.renew()
        drop.refresh_from_db()
        self.assertEqual(drop.renewal_count, 0)


# ── source_url (live API reference) ──────────────────────────────────────────

class TestSourceUrl(TestCase):

    def test_default_empty(self):
        drop = _make_db_drop(key="no-url")
        self.assertEqual(drop.source_url, "")

    def test_set_source_url(self):
        drop = _make_db_drop(key="url-set", source_url="https://api.example.com/data")
        self.assertEqual(drop.source_url, "https://api.example.com/data")

    def test_bool_check_for_source_url(self):
        drop = _make_db_drop(key="url-bool", source_url="https://api.example.com")
        self.assertTrue(bool(drop.source_url))
        empty = _make_db_drop(key="url-empty")
        self.assertFalse(bool(empty.source_url))
