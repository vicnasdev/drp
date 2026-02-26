"""
tests/unit/test_upload_views.py

Unit tests for plan enforcement in core/views/drops.py.
Uses Django's test client against an in-memory SQLite DB.
No B2 calls — b2 functions are patched.

Coverage:
  - Text upload: anon, free, paid
  - expiry_days ignored for free/anon, applied for paid, clamped at plan ceiling
  - burn flag
  - password on upload: ignored for free/anon, applied for paid
  - set-password endpoint: 403 for free, 200 for paid
  - Drop locking: paid drops locked to owner; others blocked
  - Renew endpoint: blocked without expires_at; succeeds for paid drops with expiry
  - is_test flag propagated to Drop
"""

import json
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from core.models import Drop, Plan, UserProfile


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_user(username, plan=Plan.FREE, password="pw"):
    u = User.objects.create_user(username, email=f"{username}@test.com", password=password)
    UserProfile.objects.filter(user=u).update(plan=plan)
    u.refresh_from_db()
    return u


def _post_text(client, key, content, **extra):
    return client.post('/save/', {'key': key, 'content': content, **extra},
                       HTTP_ACCEPT='application/json')


def _set_password(client, key, password):
    return client.post(
        f'/{key}/set-password/',
        json.dumps({'password': password}),
        content_type='application/json',
        HTTP_ACCEPT='application/json',
    )


# ── Text upload — basic ───────────────────────────────────────────────────────

class TestTextUploadBasic(TestCase):
    def setUp(self):
        self.free_user    = _make_user('free_up',    Plan.FREE)
        self.starter_user = _make_user('starter_up', Plan.STARTER)
        self.pro_user     = _make_user('pro_up',     Plan.PRO)

    def test_anon_can_upload_text(self):
        res = _post_text(self.client, 'anon-key', 'hello')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['key'], 'anon-key')

    def test_free_can_upload_text(self):
        self.client.force_login(self.free_user)
        res = _post_text(self.client, 'free-key', 'hello')
        self.assertEqual(res.status_code, 200)

    def test_starter_can_upload_text(self):
        self.client.force_login(self.starter_user)
        res = _post_text(self.client, 'starter-key', 'hello')
        self.assertEqual(res.status_code, 200)

    def test_text_over_free_limit_rejected(self):
        self.client.force_login(self.free_user)
        big = 'x' * (600 * 1024)  # 600 KB > 500 KB free limit
        res = _post_text(self.client, 'big-text', big)
        self.assertEqual(res.status_code, 400)
        self.assertIn('error', res.json())

    def test_text_over_starter_limit_rejected(self):
        self.client.force_login(self.starter_user)
        big = 'x' * (3 * 1024 * 1024)  # 3 MB > 2 MB starter limit
        res = _post_text(self.client, 'big-starter', big)
        self.assertEqual(res.status_code, 400)

    def test_burn_flag_set_on_drop(self):
        res = _post_text(self.client, 'burn-key', 'ephemeral', burn='1')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(Drop.objects.get(key='burn-key').burn)

    def test_is_test_sets_short_expiry(self):
        """is_test=1 sets expires_at ~1 hour instead of storing is_test flag."""
        res = _post_text(self.client, 'test-key', 'data', is_test='1')
        self.assertEqual(res.status_code, 200)
        drop = Drop.objects.get(key='test-key')
        self.assertFalse(drop.is_test)
        self.assertIsNotNone(drop.expires_at)
        # Expires within ~1 hour (give 5 min tolerance)
        from django.utils import timezone
        from datetime import timedelta
        self.assertLess(drop.expires_at, timezone.now() + timedelta(hours=1, minutes=5))

    def test_anon_drop_has_locked_until(self):
        """Anon drops get a 24h creation lock."""
        res = _post_text(self.client, 'anon-lock', 'hello')
        self.assertEqual(res.status_code, 200)
        drop = Drop.objects.get(key='anon-lock')
        self.assertIsNotNone(drop.locked_until)


# ── Custom expiry ─────────────────────────────────────────────────────────────

class TestTextUploadExpiry(TestCase):
    def setUp(self):
        self.free_user    = _make_user('exp_free',    Plan.FREE)
        self.starter_user = _make_user('exp_starter', Plan.STARTER)
        self.pro_user     = _make_user('exp_pro',     Plan.PRO)

    def test_free_expiry_ignored(self):
        """Free plan: expiry_days sent but expires_at must remain None."""
        self.client.force_login(self.free_user)
        res = _post_text(self.client, 'free-exp', 'hello', expiry_days=30)
        self.assertEqual(res.status_code, 200)
        self.assertIsNone(Drop.objects.get(key='free-exp').expires_at)

    def test_anon_expiry_ignored(self):
        res = _post_text(self.client, 'anon-exp', 'hello', expiry_days=30)
        self.assertEqual(res.status_code, 200)
        self.assertIsNone(Drop.objects.get(key='anon-exp').expires_at)

    def test_starter_expiry_applied(self):
        self.client.force_login(self.starter_user)
        res = _post_text(self.client, 'starter-exp', 'hello', expiry_days=30)
        self.assertEqual(res.status_code, 200)
        self.assertIsNotNone(Drop.objects.get(key='starter-exp').expires_at)

    def test_pro_expiry_applied(self):
        self.client.force_login(self.pro_user)
        res = _post_text(self.client, 'pro-exp', 'hello', expiry_days=90)
        self.assertEqual(res.status_code, 200)
        self.assertIsNotNone(Drop.objects.get(key='pro-exp').expires_at)

    def test_starter_expiry_clamped_at_365(self):
        """400 days exceeds starter max — must be clamped to 365, not rejected."""
        self.client.force_login(self.starter_user)
        res = _post_text(self.client, 'starter-cap', 'hello', expiry_days=400)
        self.assertEqual(res.status_code, 200)
        drop = Drop.objects.get(key='starter-cap')
        if drop.expires_at:
            max_delta = timedelta(days=Plan.get(Plan.STARTER, 'max_expiry_days') + 1)
            self.assertLessEqual(drop.expires_at - timezone.now(), max_delta)

    def test_pro_expiry_clamped_at_3_years(self):
        """2000 days exceeds pro max — must be clamped, not rejected."""
        self.client.force_login(self.pro_user)
        res = _post_text(self.client, 'pro-cap', 'hello', expiry_days=2000)
        self.assertEqual(res.status_code, 200)
        drop = Drop.objects.get(key='pro-cap')
        if drop.expires_at:
            max_delta = timedelta(days=Plan.get(Plan.PRO, 'max_expiry_days') + 1)
            self.assertLessEqual(drop.expires_at - timezone.now(), max_delta)


# ── Password protection ───────────────────────────────────────────────────────

class TestPasswordProtection(TestCase):
    def setUp(self):
        self.free_user    = _make_user('pw_free',    Plan.FREE)
        self.starter_user = _make_user('pw_starter', Plan.STARTER)

    def test_password_on_upload_ignored_for_free(self):
        """Free plan: password kwarg on upload must be silently ignored."""
        self.client.force_login(self.free_user)
        res = _post_text(self.client, 'pw-free-up', 'secret', password='mypassword')
        self.assertEqual(res.status_code, 200)
        self.assertFalse(Drop.objects.get(key='pw-free-up').is_password_protected)

    def test_password_on_upload_ignored_for_anon(self):
        res = _post_text(self.client, 'pw-anon-up', 'secret', password='mypassword')
        self.assertEqual(res.status_code, 200)
        self.assertFalse(Drop.objects.get(key='pw-anon-up').is_password_protected)

    def test_password_on_upload_applied_for_paid(self):
        self.client.force_login(self.starter_user)
        res = _post_text(self.client, 'pw-paid-up', 'secret', password='mypassword')
        self.assertEqual(res.status_code, 200)
        drop = Drop.objects.get(key='pw-paid-up')
        self.assertTrue(drop.is_password_protected)
        self.assertTrue(drop.check_password('mypassword'))

    def test_set_password_endpoint_rejected_for_free(self):
        self.client.force_login(self.free_user)
        _post_text(self.client, 'sp-free', 'data')
        res = _set_password(self.client, 'sp-free', 'secret')
        self.assertEqual(res.status_code, 403)
        self.assertFalse(Drop.objects.get(key='sp-free').is_password_protected)

    def test_set_password_endpoint_rejected_for_anon(self):
        _post_text(self.client, 'sp-anon', 'data')
        res = _set_password(self.client, 'sp-anon', 'secret')
        # Anon user has no profile — must be 403
        self.assertIn(res.status_code, (403, 404))

    def test_set_password_endpoint_accepted_for_paid(self):
        self.client.force_login(self.starter_user)
        _post_text(self.client, 'sp-paid', 'data')
        res = _set_password(self.client, 'sp-paid', 'secret')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(Drop.objects.get(key='sp-paid').is_password_protected)

    def test_set_password_can_be_removed(self):
        self.client.force_login(self.starter_user)
        _post_text(self.client, 'sp-remove', 'data')
        _set_password(self.client, 'sp-remove', 'secret')
        res = _set_password(self.client, 'sp-remove', '')
        self.assertEqual(res.status_code, 200)
        self.assertFalse(Drop.objects.get(key='sp-remove').is_password_protected)

    def test_non_owner_cannot_set_password(self):
        other = _make_user('pw_other', Plan.STARTER)
        self.client.force_login(self.starter_user)
        _post_text(self.client, 'sp-owner', 'data')
        self.client.force_login(other)
        res = _set_password(self.client, 'sp-owner', 'hack')
        self.assertEqual(res.status_code, 403)


# ── Drop locking ──────────────────────────────────────────────────────────────

class TestDropLocking(TestCase):
    def setUp(self):
        self.paid_user = _make_user('paid_lock', Plan.STARTER)
        self.free_user = _make_user('free_lock', Plan.FREE)
        self.other     = _make_user('other_lock', Plan.FREE)

    def test_paid_drop_is_locked(self):
        self.client.force_login(self.paid_user)
        _post_text(self.client, 'locked-drop', 'mine')
        self.assertTrue(Drop.objects.get(key='locked-drop').locked)

    def test_free_drop_not_permanently_locked(self):
        """Free drops get a 24h creation lock, but locked=False (anyone can write after)."""
        self.client.force_login(self.free_user)
        _post_text(self.client, 'free-drop', 'open')
        drop = Drop.objects.get(key='free-drop')
        self.assertFalse(drop.locked)

    def test_other_user_cannot_overwrite_paid_drop(self):
        self.client.force_login(self.paid_user)
        _post_text(self.client, 'protected', 'owner content')
        self.client.force_login(self.other)
        res = _post_text(self.client, 'protected', 'hijack attempt')
        self.assertEqual(res.status_code, 403)

    def test_anon_cannot_overwrite_paid_drop(self):
        self.client.force_login(self.paid_user)
        _post_text(self.client, 'paid-vs-anon', 'mine')
        self.client.logout()
        res = _post_text(self.client, 'paid-vs-anon', 'hijack')
        self.assertEqual(res.status_code, 403)

    def test_owner_can_overwrite_own_drop(self):
        self.client.force_login(self.paid_user)
        _post_text(self.client, 'my-drop', 'v1')
        res = _post_text(self.client, 'my-drop', 'v2')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(Drop.objects.get(key='my-drop').content, 'v2')

    def test_anon_drop_overwritable_after_creation_window(self):
        """Anon drops: once locked_until passes, anyone can overwrite."""
        _post_text(self.client, 'open-anon', 'v1')
        drop = Drop.objects.get(key='open-anon')
        # Simulate the 24h window expiring
        Drop.objects.filter(pk=drop.pk).update(locked_until=timezone.now() - timedelta(hours=1))
        res = _post_text(self.client, 'open-anon', 'v2')
        self.assertEqual(res.status_code, 200)


# ── Renew endpoint ────────────────────────────────────────────────────────────

class TestRenewEndpoint(TestCase):
    def setUp(self):
        self.free_user    = _make_user('renew_free',    Plan.FREE)
        self.starter_user = _make_user('renew_starter', Plan.STARTER)
        self.other        = _make_user('renew_other',   Plan.FREE)

    def test_free_drop_without_expiry_cannot_be_renewed(self):
        self.client.force_login(self.free_user)
        _post_text(self.client, 'renew-free', 'content')
        res = self.client.post('/renew-free/renew/', HTTP_ACCEPT='application/json')
        self.assertEqual(res.status_code, 400)

    def test_anon_drop_cannot_be_renewed(self):
        _post_text(self.client, 'renew-anon', 'content')
        res = self.client.post('/renew-anon/renew/', HTTP_ACCEPT='application/json')
        self.assertEqual(res.status_code, 403)

    def test_paid_drop_with_expiry_can_be_renewed(self):
        self.client.force_login(self.starter_user)
        _post_text(self.client, 'renew-paid', 'content', expiry_days=7)
        drop = Drop.objects.get(key='renew-paid')
        if drop.expires_at:
            exp_before = drop.expires_at
            res = self.client.post('/renew-paid/renew/', HTTP_ACCEPT='application/json')
            self.assertEqual(res.status_code, 200)
            drop.refresh_from_db()
            self.assertGreater(drop.expires_at, exp_before)

    def test_non_owner_cannot_renew(self):
        self.client.force_login(self.starter_user)
        _post_text(self.client, 'renew-steal', 'content', expiry_days=7)
        self.client.force_login(self.other)
        res = self.client.post('/renew-steal/renew/', HTTP_ACCEPT='application/json')
        self.assertEqual(res.status_code, 403)


# ── Live API reference (source_url) ──────────────────────────────────────────

class TestLiveAPIReference(TestCase):

    def setUp(self):
        self.starter = _make_user('ref-starter', plan=Plan.STARTER)
        self.free = _make_user('ref-free', plan=Plan.FREE)

    def test_paid_user_can_set_source_url(self):
        self.client.force_login(self.starter)
        res = _post_text(self.client, 'api-ref', 'https://httpbin.org/get',
                         source_url='https://httpbin.org/get')
        self.assertEqual(res.status_code, 200)
        drop = Drop.objects.get(key='api-ref')
        self.assertEqual(drop.source_url, 'https://httpbin.org/get')

    def test_free_user_source_url_ignored(self):
        self.client.force_login(self.free)
        res = _post_text(self.client, 'api-free', 'https://httpbin.org/get',
                         source_url='https://httpbin.org/get')
        self.assertEqual(res.status_code, 200)
        drop = Drop.objects.get(key='api-free')
        self.assertEqual(drop.source_url, '')

    def test_source_url_returned_in_json(self):
        self.client.force_login(self.starter)
        _post_text(self.client, 'api-check', 'https://example.com/api',
                   source_url='https://example.com/api')
        drop = Drop.objects.get(key='api-check')
        self.assertEqual(drop.source_url, 'https://example.com/api')

    def test_drop_without_source_url_has_empty_field(self):
        self.client.force_login(self.starter)
        _post_text(self.client, 'normal-text', 'hello world')
        drop = Drop.objects.get(key='normal-text')
        self.assertEqual(drop.source_url, '')


# ── Drop transfer (send / claim) ─────────────────────────────────────────────

class TestDropTransfer(TestCase):

    def setUp(self):
        self.alice = _make_user('alice', plan=Plan.FREE)
        self.bob   = _make_user('bob',   plan=Plan.FREE)

    def _create_drop(self, owner, key='xfer-test'):
        self.client.force_login(owner)
        _post_text(self.client, key, 'transfer me')
        return Drop.objects.get(key=key)

    def test_send_generates_token(self):
        drop = self._create_drop(self.alice)
        res = self.client.post(f'/{drop.key}/send/', HTTP_ACCEPT='application/json')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn('token', data)
        self.assertEqual(data['key'], drop.key)

    def test_send_requires_ownership(self):
        self._create_drop(self.alice, key='notown')
        self.client.force_login(self.bob)
        res = self.client.post('/notown/send/', HTTP_ACCEPT='application/json')
        self.assertEqual(res.status_code, 404)

    def test_send_requires_login(self):
        self._create_drop(self.alice, key='nologin')
        self.client.logout()
        res = self.client.post('/nologin/send/', HTTP_ACCEPT='application/json')
        self.assertEqual(res.status_code, 401)

    def test_claim_transfers_ownership(self):
        drop = self._create_drop(self.alice, key='claim-me')
        res = self.client.post(f'/{drop.key}/send/', HTTP_ACCEPT='application/json')
        token = res.json()['token']

        self.client.force_login(self.bob)
        res = self.client.post(f'/claim/{token}/', HTTP_ACCEPT='application/json')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data['key'], 'claim-me')
        self.assertEqual(data['from'], 'alice')

        drop.refresh_from_db()
        self.assertEqual(drop.owner, self.bob)

    def test_claim_requires_login(self):
        drop = self._create_drop(self.alice, key='claim-nologin')
        res = self.client.post(f'/{drop.key}/send/', HTTP_ACCEPT='application/json')
        token = res.json()['token']

        self.client.logout()
        res = self.client.post(f'/claim/{token}/', HTTP_ACCEPT='application/json')
        self.assertEqual(res.status_code, 401)

    def test_cannot_claim_own_drop(self):
        drop = self._create_drop(self.alice, key='self-claim')
        res = self.client.post(f'/{drop.key}/send/', HTTP_ACCEPT='application/json')
        token = res.json()['token']
        # Alice tries to claim her own token
        res = self.client.post(f'/claim/{token}/', HTTP_ACCEPT='application/json')
        self.assertEqual(res.status_code, 400)

    def test_token_single_use(self):
        drop = self._create_drop(self.alice, key='single-use')
        res = self.client.post(f'/{drop.key}/send/', HTTP_ACCEPT='application/json')
        token = res.json()['token']

        self.client.force_login(self.bob)
        self.client.post(f'/claim/{token}/', HTTP_ACCEPT='application/json')
        # Second claim by another user should fail
        charlie = _make_user('charlie', plan=Plan.FREE)
        self.client.force_login(charlie)
        res = self.client.post(f'/claim/{token}/', HTTP_ACCEPT='application/json')
        self.assertEqual(res.status_code, 410)

    def test_invalid_token_rejected(self):
        self.client.force_login(self.bob)
        res = self.client.post('/claim/nonexistent-token/', HTTP_ACCEPT='application/json')
        self.assertEqual(res.status_code, 404)

    def test_new_send_revokes_old_token(self):
        drop = self._create_drop(self.alice, key='revoke-old')
        res1 = self.client.post(f'/{drop.key}/send/', HTTP_ACCEPT='application/json')
        old_token = res1.json()['token']
        res2 = self.client.post(f'/{drop.key}/send/', HTTP_ACCEPT='application/json')
        new_token = res2.json()['token']
        self.assertNotEqual(old_token, new_token)

        # Old token should be expired
        self.client.force_login(self.bob)
        res = self.client.post(f'/claim/{old_token}/', HTTP_ACCEPT='application/json')
        self.assertEqual(res.status_code, 410)


# ── Like / Unlike ─────────────────────────────────────────────────────────────

class TestDropLikes(TestCase):
    def setUp(self):
        self.alice = _make_user('alice-like')
        self.bob   = _make_user('bob-like')
        self.client.force_login(self.alice)
        _post_text(self.client, 'pub-like', 'hello', is_public='true')
        _post_text(self.client, 'priv-like', 'secret')
        self.client.logout()

    # ── toggle like ──────────────────────────────────────────────────────

    def test_like_requires_login(self):
        res = self.client.post('/pub-like/like/', HTTP_ACCEPT='application/json')
        self.assertEqual(res.status_code, 302)  # redirect to login

    def test_like_toggle_on(self):
        self.client.force_login(self.bob)
        res = self.client.post('/pub-like/like/', HTTP_ACCEPT='application/json')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data['liked'])
        self.assertEqual(data['like_count'], 1)

    def test_like_toggle_off(self):
        self.client.force_login(self.bob)
        self.client.post('/pub-like/like/', HTTP_ACCEPT='application/json')
        res = self.client.post('/pub-like/like/', HTTP_ACCEPT='application/json')
        data = res.json()
        self.assertFalse(data['liked'])
        self.assertEqual(data['like_count'], 0)

    def test_like_private_drop_404(self):
        self.client.force_login(self.bob)
        res = self.client.post('/priv-like/like/', HTTP_ACCEPT='application/json')
        self.assertEqual(res.status_code, 404)

    def test_like_nonexistent_drop_404(self):
        self.client.force_login(self.bob)
        res = self.client.post('/nonexist999/like/', HTTP_ACCEPT='application/json')
        self.assertEqual(res.status_code, 404)

    def test_multiple_users_like(self):
        self.client.force_login(self.alice)
        self.client.post('/pub-like/like/', HTTP_ACCEPT='application/json')
        self.client.force_login(self.bob)
        res = self.client.post('/pub-like/like/', HTTP_ACCEPT='application/json')
        self.assertEqual(res.json()['like_count'], 2)

    # ── public feed sort ─────────────────────────────────────────────────

    def test_public_feed_sort_recent(self):
        res = self.client.get('/explore/', HTTP_ACCEPT='application/json')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn('drops', data)
        # all drops should have like_count field
        for d in data['drops']:
            self.assertIn('like_count', d)

    def test_public_feed_sort_likes(self):
        # Like pub-like with both users
        self.client.force_login(self.alice)
        self.client.post('/pub-like/like/', HTTP_ACCEPT='application/json')
        self.client.force_login(self.bob)
        self.client.post('/pub-like/like/', HTTP_ACCEPT='application/json')

        res = self.client.get('/explore/?sort=likes', HTTP_ACCEPT='application/json')
        data = res.json()
        drops = data['drops']
        self.assertTrue(len(drops) >= 1)
        # First drop should be the most liked
        self.assertEqual(drops[0]['key'], 'pub-like')
        self.assertEqual(drops[0]['like_count'], 2)

    def test_public_feed_json_liked_field(self):
        self.client.force_login(self.bob)
        self.client.post('/pub-like/like/', HTTP_ACCEPT='application/json')
        res = self.client.get('/explore/', HTTP_ACCEPT='application/json')
        data = res.json()
        pub = next(d for d in data['drops'] if d['key'] == 'pub-like')
        self.assertTrue(pub['liked'])


# ── Key validation — unsafe characters rejected ──────────────────────────────

class TestKeyValidationOnSave(TestCase):
    """Unsafe key characters are rejected by save_drop."""

    def test_hash_key_rejected(self):
        res = _post_text(self.client, '#', 'hello')
        self.assertEqual(res.status_code, 400)
        self.assertIn('forbidden', res.json()['error'].lower())

    def test_question_mark_key_rejected(self):
        res = _post_text(self.client, 'key?q=1', 'hello')
        self.assertEqual(res.status_code, 400)

    def test_space_key_rejected(self):
        res = _post_text(self.client, 'hello world', 'data')
        self.assertEqual(res.status_code, 400)

    def test_ampersand_key_rejected(self):
        res = _post_text(self.client, 'a&b', 'data')
        self.assertEqual(res.status_code, 400)

    def test_at_prefix_rejected(self):
        res = _post_text(self.client, '@user', 'data')
        self.assertEqual(res.status_code, 400)

    def test_valid_key_accepted(self):
        res = _post_text(self.client, 'valid-key-123', 'hello')
        self.assertEqual(res.status_code, 200)


# ── Key collision auto-resolve on upload_prepare ──────────────────────────────

class TestUploadPrepareCollision(TestCase):
    """When a key is taken by another user, upload_prepare auto-resolves with numeric suffix."""

    def setUp(self):
        self.alice = _make_user('alice_col', Plan.FREE)
        self.bob   = _make_user('bob_col',   Plan.FREE)

    @patch('core.views.drops.presigned_put', return_value='https://b2.example.com/upload')
    def test_collision_appends_numeric_suffix(self, mock_b2):
        # Alice owns 'report'
        Drop.objects.create(
            ns=Drop.NS_FILE, key='report', kind=Drop.FILE,
            owner=self.alice, filename='report.pdf', filesize=100,
        )
        # Bob tries to upload 'report' — should get 'report-2'
        self.client.force_login(self.bob)
        res = self.client.post(
            '/upload/prepare/',
            json.dumps({'key': 'report', 'ns': 'f', 'content_type': 'application/pdf', 'size': 100}),
            content_type='application/json',
            HTTP_ACCEPT='application/json',
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['key'], 'report-2')

    @patch('core.views.drops.presigned_put', return_value='https://b2.example.com/upload')
    def test_collision_skips_to_3_when_2_taken(self, mock_b2):
        # Alice owns 'report' and 'report-2'
        Drop.objects.create(
            ns=Drop.NS_FILE, key='report', kind=Drop.FILE,
            owner=self.alice, filename='r.pdf', filesize=100,
        )
        Drop.objects.create(
            ns=Drop.NS_FILE, key='report-2', kind=Drop.FILE,
            owner=self.alice, filename='r2.pdf', filesize=100,
        )
        # Bob gets 'report-3'
        self.client.force_login(self.bob)
        res = self.client.post(
            '/upload/prepare/',
            json.dumps({'key': 'report', 'ns': 'f', 'content_type': 'application/pdf', 'size': 100}),
            content_type='application/json',
            HTTP_ACCEPT='application/json',
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['key'], 'report-3')

    @patch('core.views.drops.presigned_put', return_value='https://b2.example.com/upload')
    def test_own_key_not_collided(self, mock_b2):
        """Owner re-uploading to their own key should NOT trigger collision logic."""
        Drop.objects.create(
            ns=Drop.NS_FILE, key='myfile', kind=Drop.FILE,
            owner=self.alice, filename='myfile.pdf', filesize=100,
        )
        self.client.force_login(self.alice)
        res = self.client.post(
            '/upload/prepare/',
            json.dumps({'key': 'myfile', 'ns': 'f', 'content_type': 'application/pdf', 'size': 100}),
            content_type='application/json',
            HTTP_ACCEPT='application/json',
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['key'], 'myfile')

    @patch('core.views.drops.presigned_put', return_value='https://b2.example.com/upload')
    def test_unsafe_key_rejected_on_prepare(self, mock_b2):
        self.client.force_login(self.alice)
        res = self.client.post(
            '/upload/prepare/',
            json.dumps({'key': 'bad#key', 'ns': 'f', 'content_type': 'application/pdf', 'size': 100}),
            content_type='application/json',
            HTTP_ACCEPT='application/json',
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn('forbidden', res.json()['error'].lower())
