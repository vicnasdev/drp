"""
tests/unit/test_storage_and_helpers.py

Unit tests for storage accounting, plan helper functions, anon drop claiming,
and key validation.
"""

from unittest.mock import MagicMock

from django.contrib.auth.models import User
from django.test import TestCase

from core.models import Drop, Plan, UserProfile
from core.views.helpers import (
    user_plan, max_file_bytes, max_text_bytes, storage_ok,
    is_paid_user, max_lifetime_secs, claim_anon_drops,
    is_valid_drop_key, invalid_key_message,
)


def _make_user(username, plan=Plan.FREE):
    u = User.objects.create_user(username, password="pw")
    UserProfile.objects.filter(user=u).update(plan=plan)
    u.refresh_from_db()
    return u


# ── user_plan ─────────────────────────────────────────────────────────────────

class TestUserPlan(TestCase):
    def test_anon_user_returns_anon_plan(self):
        anon = MagicMock(is_authenticated=False)
        self.assertEqual(user_plan(anon), Plan.ANON)

    def test_free_user_returns_free_plan(self):
        u = _make_user('up_free')
        self.assertEqual(user_plan(u), Plan.FREE)

    def test_starter_user_returns_starter_plan(self):
        u = _make_user('up_starter', Plan.STARTER)
        self.assertEqual(user_plan(u), Plan.STARTER)

    def test_pro_user_returns_pro_plan(self):
        u = _make_user('up_pro', Plan.PRO)
        self.assertEqual(user_plan(u), Plan.PRO)


# ── max_file_bytes / max_text_bytes ───────────────────────────────────────────

class TestMaxBytes(TestCase):
    def test_anon_max_file_200mb(self):
        anon = MagicMock(is_authenticated=False)
        self.assertEqual(max_file_bytes(anon), 200 * 1024 * 1024)

    def test_pro_max_file_5gb(self):
        u = _make_user('mb_pro', Plan.PRO)
        self.assertEqual(max_file_bytes(u), 5120 * 1024 * 1024)

    def test_free_max_text_500kb(self):
        u = _make_user('mt_free')
        self.assertEqual(max_text_bytes(u), 500 * 1024)

    def test_pro_max_text_10mb(self):
        u = _make_user('mt_pro', Plan.PRO)
        self.assertEqual(max_text_bytes(u), 10240 * 1024)


# ── storage_ok ────────────────────────────────────────────────────────────────

class TestStorageOk(TestCase):
    def test_anon_always_ok(self):
        anon = MagicMock(is_authenticated=False)
        self.assertTrue(storage_ok(anon, 999_999_999))

    def test_free_always_ok_no_quota(self):
        u = _make_user('so_free')
        self.assertTrue(storage_ok(u, 999_999_999))

    def test_starter_within_quota_ok(self):
        u = _make_user('so_starter', Plan.STARTER)
        UserProfile.objects.filter(user=u).update(storage_used_bytes=0)
        u.profile.refresh_from_db()
        self.assertTrue(storage_ok(u, 1024))

    def test_starter_over_quota_not_ok(self):
        u = _make_user('so_starter2', Plan.STARTER)
        quota = 5 * 1024 ** 3
        UserProfile.objects.filter(user=u).update(storage_used_bytes=quota)
        u.profile.refresh_from_db()
        self.assertFalse(storage_ok(u, 1))


# ── is_paid_user ──────────────────────────────────────────────────────────────

class TestIsPaidUser(TestCase):
    def test_anon_not_paid(self):
        anon = MagicMock(is_authenticated=False)
        self.assertFalse(is_paid_user(anon))

    def test_free_not_paid(self):
        u = _make_user('ip_free')
        self.assertFalse(is_paid_user(u))

    def test_starter_is_paid(self):
        u = _make_user('ip_starter', Plan.STARTER)
        self.assertTrue(is_paid_user(u))

    def test_pro_is_paid(self):
        u = _make_user('ip_pro', Plan.PRO)
        self.assertTrue(is_paid_user(u))


# ── max_lifetime_secs ─────────────────────────────────────────────────────────

class TestMaxLifetimeSecs(TestCase):
    def test_anon_clipboard_7_days(self):
        anon = MagicMock(is_authenticated=False)
        expected = 7 * 24 * 3600
        self.assertEqual(max_lifetime_secs(anon, Drop.NS_CLIPBOARD), expected)

    def test_free_clipboard_30_days(self):
        u = _make_user('ml_free')
        expected = 30 * 24 * 3600
        self.assertEqual(max_lifetime_secs(u, Drop.NS_CLIPBOARD), expected)

    def test_paid_clipboard_no_ceiling(self):
        u = _make_user('ml_starter', Plan.STARTER)
        self.assertIsNone(max_lifetime_secs(u, Drop.NS_CLIPBOARD))

    def test_file_drop_always_none(self):
        anon = MagicMock(is_authenticated=False)
        self.assertIsNone(max_lifetime_secs(anon, Drop.NS_FILE))


# ── claim_anon_drops ──────────────────────────────────────────────────────────

class TestClaimAnonDrops(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("claimer", password="pw")

    def _make_anon_drop(self, key, token="tok123"):
        return Drop.objects.create(
            ns=Drop.NS_CLIPBOARD, key=key, kind=Drop.TEXT,
            content="hello", anon_token=token, owner=None,
        )

    def test_claims_drops_with_matching_token(self):
        self._make_anon_drop('claim-me')
        count = claim_anon_drops(self.user, 'tok123')
        self.assertEqual(count, 1)
        self.assertEqual(Drop.objects.get(key='claim-me').owner, self.user)

    def test_does_not_claim_different_token(self):
        self._make_anon_drop('other', token='other-tok')
        count = claim_anon_drops(self.user, 'tok123')
        self.assertEqual(count, 0)
        self.assertIsNone(Drop.objects.get(key='other').owner)

    def test_empty_token_returns_zero(self):
        self._make_anon_drop('unclaimed')
        count = claim_anon_drops(self.user, '')
        self.assertEqual(count, 0)

    def test_none_token_returns_zero(self):
        count = claim_anon_drops(self.user, None)
        self.assertEqual(count, 0)

    def test_claimed_drop_gets_locked(self):
        self._make_anon_drop('lock-on-claim')
        claim_anon_drops(self.user, 'tok123')
        self.assertTrue(Drop.objects.get(key='lock-on-claim').locked)

    def test_claimed_drop_gets_free_lifetime(self):
        self._make_anon_drop('lifetime-claim')
        claim_anon_drops(self.user, 'tok123')
        drop = Drop.objects.get(key='lifetime-claim')
        expected = 30 * 24 * 3600
        self.assertEqual(drop.max_lifetime_secs, expected)

    def test_multiple_drops_same_token_all_claimed(self):
        for i in range(3):
            self._make_anon_drop(f'multi-{i}')
        count = claim_anon_drops(self.user, 'tok123')
        self.assertEqual(count, 3)


# ── Storage signal: post_delete ───────────────────────────────────────────────

class TestStorageSignal(TestCase):
    def setUp(self):
        self.user = _make_user('sig_user', Plan.STARTER)

    def test_storage_decremented_on_drop_delete(self):
        from unittest.mock import patch
        drop = Drop.objects.create(
            ns=Drop.NS_FILE, key='sig-del', kind=Drop.FILE,
            file_public_id='drops/f/sig-del', filename='sig.pdf',
            filesize=1024, owner=self.user,
        )
        UserProfile.objects.filter(user=self.user).update(storage_used_bytes=1024)
        with patch('core.views.b2.delete_object'):
            drop.hard_delete()
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.storage_used_bytes, 0)

    def test_storage_never_goes_negative(self):
        from unittest.mock import patch
        drop = Drop.objects.create(
            ns=Drop.NS_FILE, key='sig-neg', kind=Drop.FILE,
            file_public_id='drops/f/sig-neg', filename='n.pdf',
            filesize=5000, owner=self.user,
        )
        # storage_used_bytes is 0 but we delete a 5 KB file — should clamp at 0
        UserProfile.objects.filter(user=self.user).update(storage_used_bytes=0)
        with patch('core.views.b2.delete_object'):
            drop.hard_delete()
        self.user.profile.refresh_from_db()
        self.assertGreaterEqual(self.user.profile.storage_used_bytes, 0)


# ── is_valid_drop_key / invalid_key_message ───────────────────────────────────

class TestIsValidDropKey(TestCase):
    """Key validation: rejects empty, @-prefixed, and URL-unsafe characters."""

    def test_normal_key_valid(self):
        self.assertTrue(is_valid_drop_key('my-report'))

    def test_alphanumeric_with_hyphens_valid(self):
        self.assertTrue(is_valid_drop_key('hello-world-2'))

    def test_empty_key_invalid(self):
        self.assertFalse(is_valid_drop_key(''))

    def test_at_prefix_invalid(self):
        self.assertFalse(is_valid_drop_key('@user'))

    def test_hash_invalid(self):
        self.assertFalse(is_valid_drop_key('my#key'))

    def test_question_mark_invalid(self):
        self.assertFalse(is_valid_drop_key('key?value'))

    def test_percent_invalid(self):
        self.assertFalse(is_valid_drop_key('100%done'))

    def test_ampersand_invalid(self):
        self.assertFalse(is_valid_drop_key('a&b'))

    def test_space_invalid(self):
        self.assertFalse(is_valid_drop_key('my key'))

    def test_slash_invalid(self):
        self.assertFalse(is_valid_drop_key('path/to'))

    def test_backslash_invalid(self):
        self.assertFalse(is_valid_drop_key('path\\to'))

    def test_colon_invalid(self):
        self.assertFalse(is_valid_drop_key('file:name'))

    def test_brackets_invalid(self):
        self.assertFalse(is_valid_drop_key('arr[0]'))

    def test_bare_hash_invalid(self):
        self.assertFalse(is_valid_drop_key('#'))

    def test_dots_and_underscores_valid(self):
        self.assertTrue(is_valid_drop_key('my_file.v2'))

    def test_unicode_valid(self):
        self.assertTrue(is_valid_drop_key('café'))


class TestInvalidKeyMessage(TestCase):
    def test_valid_key_returns_none(self):
        self.assertIsNone(invalid_key_message('good-key'))

    def test_empty_key_message(self):
        msg = invalid_key_message('')
        self.assertIn('empty', msg.lower())

    def test_at_prefix_message(self):
        msg = invalid_key_message('@user')
        self.assertIn('@', msg)

    def test_forbidden_chars_message(self):
        msg = invalid_key_message('a#b?c')
        self.assertIn('#', msg)
        self.assertIn('?', msg)
        self.assertIn('forbidden', msg.lower())
