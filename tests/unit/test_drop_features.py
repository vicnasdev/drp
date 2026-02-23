"""
tests/unit/test_drop_features.py

Unit tests for burn, scheduled drops (visible_from), webhooks, and aliases.
"""

from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from core.models import Alias, Drop, Plan, UserProfile


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_user(username, plan=Plan.FREE, password="pw"):
    u = User.objects.create_user(username, email=f"{username}@test.com", password=password)
    UserProfile.objects.filter(user=u).update(plan=plan)
    u.refresh_from_db()
    return u


def _post_text(client, key, content, **extra):
    return client.post('/save/', {'key': key, 'content': content, **extra},
                       HTTP_ACCEPT='application/json')


# ── Burn ──────────────────────────────────────────────────────────────────────

class TestBurnBehaviour(TestCase):
    """Burn drops are deleted on first read, not before."""

    def test_burn_drop_exists_before_read(self):
        _post_text(self.client, 'burn-exists', 'secret', burn='1')
        self.assertTrue(Drop.objects.filter(key='burn-exists').exists())

    def test_burn_drop_deleted_after_json_read(self):
        _post_text(self.client, 'burn-read', 'secret', burn='1')
        # First read should return content
        res = self.client.get('/burn-read/', HTTP_ACCEPT='application/json')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['content'], 'secret')
        # Drop should be gone
        self.assertFalse(Drop.objects.filter(key='burn-read').exists())

    def test_burn_drop_second_read_404(self):
        _post_text(self.client, 'burn-twice', 'secret', burn='1')
        self.client.get('/burn-twice/', HTTP_ACCEPT='application/json')
        res = self.client.get('/burn-twice/', HTTP_ACCEPT='application/json')
        self.assertEqual(res.status_code, 404)

    def test_burn_drop_raw_view_deletes(self):
        _post_text(self.client, 'burn-raw', 'secret', burn='1')
        res = self.client.get('/raw/burn-raw/')
        self.assertEqual(res.status_code, 200)
        self.assertFalse(Drop.objects.filter(key='burn-raw').exists())

    def test_non_burn_drop_survives_read(self):
        _post_text(self.client, 'no-burn', 'persistent')
        self.client.get('/no-burn/', HTTP_ACCEPT='application/json')
        self.assertTrue(Drop.objects.filter(key='no-burn').exists())

    def test_burn_with_password(self):
        """Burn + password: correct password reveals and deletes."""
        user = _make_user('burn_pw', Plan.STARTER)
        self.client.force_login(user)
        _post_text(self.client, 'burn-pw', 'secret', burn='1', password='pass123')
        self.client.logout()
        # Wrong password — still exists
        res = self.client.get('/burn-pw/', HTTP_ACCEPT='application/json')
        self.assertEqual(res.status_code, 401)
        self.assertTrue(Drop.objects.filter(key='burn-pw').exists())
        # Right password — returns content and burns
        res = self.client.get('/burn-pw/', HTTP_ACCEPT='application/json',
                              HTTP_X_DROP_PASSWORD='pass123')
        self.assertEqual(res.status_code, 200)
        self.assertFalse(Drop.objects.filter(key='burn-pw').exists())


# ── Expiry ────────────────────────────────────────────────────────────────────

class TestExpiryBehaviour(TestCase):
    """Expiry applied, clamped, ignored for free — focus on model + view interaction."""

    def test_expired_drop_returns_410(self):
        """A drop whose expires_at is in the past returns 410 Gone."""
        drop = Drop.objects.create(
            ns='c', key='expired-drop', kind=Drop.TEXT, content='old',
            expires_at=timezone.now() - timedelta(hours=1),
        )
        res = self.client.get('/expired-drop/', HTTP_ACCEPT='application/json')
        self.assertEqual(res.status_code, 410)
        # Drop should be hard-deleted from DB
        self.assertFalse(Drop.objects.filter(key='expired-drop').exists())

    def test_not_yet_expired_drop_accessible(self):
        drop = Drop.objects.create(
            ns='c', key='fresh-drop', kind=Drop.TEXT, content='current',
            expires_at=timezone.now() + timedelta(days=7),
        )
        res = self.client.get('/fresh-drop/', HTTP_ACCEPT='application/json')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['content'], 'current')

    def test_clipboard_idle_expiry(self):
        """Clipboard drop with no explicit expiry expires after idle period."""
        drop = Drop.objects.create(
            ns='c', key='idle-drop', kind=Drop.TEXT, content='stale',
        )
        # Simulate created 48+ hours ago with no access
        Drop.objects.filter(pk=drop.pk).update(
            created_at=timezone.now() - timedelta(hours=49),
        )
        drop.refresh_from_db()
        self.assertTrue(drop.is_expired())


# ── Scheduled drops (visible_from) ───────────────────────────────────────────

class TestScheduledDrops(TestCase):
    """Drops with visible_from should be pending until the time comes."""

    def test_is_visible_false_before_scheduled_time(self):
        drop = Drop.objects.create(
            ns='c', key='scheduled-future', kind=Drop.TEXT, content='later',
            visible_from=timezone.now() + timedelta(hours=2),
        )
        self.assertFalse(drop.is_visible)

    def test_is_visible_true_after_scheduled_time(self):
        drop = Drop.objects.create(
            ns='c', key='scheduled-past', kind=Drop.TEXT, content='now',
            visible_from=timezone.now() - timedelta(hours=1),
        )
        self.assertTrue(drop.is_visible)

    def test_is_visible_true_when_no_schedule(self):
        drop = Drop.objects.create(
            ns='c', key='no-schedule', kind=Drop.TEXT, content='immediate',
        )
        self.assertTrue(drop.is_visible)

    def test_model_property_consistency(self):
        """visible_from=None and visible_from in the past both yield is_visible=True."""
        d1 = Drop(visible_from=None)
        d2 = Drop(visible_from=timezone.now() - timedelta(seconds=1))
        self.assertTrue(d1.is_visible)
        self.assertTrue(d2.is_visible)


# ── Webhook model ─────────────────────────────────────────────────────────────

class TestWebhookField(TestCase):
    """Webhook URL stored on drop, fires on access (behaviour tested when view wiring is done)."""

    def test_webhook_url_stored(self):
        user = _make_user('wh_user', Plan.STARTER)
        drop = Drop.objects.create(
            ns='c', key='wh-drop', kind=Drop.TEXT, content='hook me',
            owner=user,
            webhook_url='https://example.com/hook',
        )
        drop.refresh_from_db()
        self.assertEqual(drop.webhook_url, 'https://example.com/hook')

    def test_webhook_url_empty_by_default(self):
        drop = Drop.objects.create(
            ns='c', key='no-wh', kind=Drop.TEXT, content='plain',
        )
        self.assertEqual(drop.webhook_url, '')

    def test_notify_before_secs_stored(self):
        drop = Drop.objects.create(
            ns='c', key='notify-drop', kind=Drop.TEXT, content='notify',
            notify_before_secs=604800,  # 7 days
            expires_at=timezone.now() + timedelta(days=30),
        )
        drop.refresh_from_db()
        self.assertEqual(drop.notify_before_secs, 604800)


# ── Alias ─────────────────────────────────────────────────────────────────────

class TestAliasModel(TestCase):
    """Alias resolves correctly at the model level."""

    def test_create_alias(self):
        user = _make_user('alias_user')
        Drop.objects.create(ns='c', key='real-key', kind=Drop.TEXT, content='hi', owner=user)
        alias = Alias.objects.create(owner=user, alias='shortcut', ns='c', key='real-key')
        self.assertEqual(str(alias), '@alias_user/shortcut → /real-key/')

    def test_alias_unique_per_owner(self):
        user = _make_user('alias_uniq')
        Alias.objects.create(owner=user, alias='myalias', ns='c', key='key1')
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            Alias.objects.create(owner=user, alias='myalias', ns='c', key='key2')

    def test_alias_resolves_to_drop(self):
        user = _make_user('alias_resolve')
        Drop.objects.create(ns='c', key='target-key', kind=Drop.TEXT, content='found', owner=user)
        alias = Alias.objects.create(owner=user, alias='friendly', ns='c', key='target-key')
        # Simulate resolution
        drop = Drop.objects.filter(ns=alias.ns, key=alias.key).first()
        self.assertIsNotNone(drop)
        self.assertEqual(drop.content, 'found')

    def test_different_users_same_alias(self):
        u1 = _make_user('alias_u1')
        u2 = _make_user('alias_u2')
        Alias.objects.create(owner=u1, alias='shared', ns='c', key='k1')
        Alias.objects.create(owner=u2, alias='shared', ns='c', key='k2')
        self.assertEqual(Alias.objects.filter(alias='shared').count(), 2)


# ── Collection Inbox ─────────────────────────────────────────────────────────

class TestCollectionInbox(TestCase):
    """Public inbox: anyone can POST text to a public_inbox collection."""

    def setUp(self):
        from core.models import Collection
        self.owner = _make_user('inbox_owner', plan=Plan.STARTER)
        self.col = Collection.objects.create(
            owner=self.owner, name='inbox-col', slug='inbox-col', public_inbox=True
        )

    def test_post_to_public_inbox_creates_drop(self):
        import json as _json
        res = self.client.post(
            f'/@{self.owner.username}/inbox-col/',
            data=_json.dumps({"content": "hello from anon"}),
            content_type='application/json',
        )
        self.assertEqual(res.status_code, 201)
        data = res.json()
        self.assertIn('key', data)
        self.assertTrue(Drop.objects.filter(key=data['key']).exists())

    def test_post_to_non_inbox_rejected(self):
        import json as _json
        self.col.public_inbox = False
        self.col.save(update_fields=['public_inbox'])
        res = self.client.post(
            f'/@{self.owner.username}/inbox-col/',
            data=_json.dumps({"content": "should fail"}),
            content_type='application/json',
        )
        self.assertEqual(res.status_code, 403)

    def test_empty_content_rejected(self):
        import json as _json
        res = self.client.post(
            f'/@{self.owner.username}/inbox-col/',
            data=_json.dumps({"content": ""}),
            content_type='application/json',
        )
        self.assertEqual(res.status_code, 400)

    def test_toggle_inbox(self):
        self.client.force_login(self.owner)
        res = self.client.post(f'/collections/{self.col.pk}/toggle-inbox/')
        self.assertEqual(res.status_code, 200)
        self.col.refresh_from_db()
        self.assertFalse(self.col.public_inbox)  # was True, now False

    def test_toggle_inbox_non_owner_rejected(self):
        other = _make_user('inbox_other')
        self.client.force_login(other)
        res = self.client.post(f'/collections/{self.col.pk}/toggle-inbox/')
        self.assertEqual(res.status_code, 403)


# ── Public Feed ──────────────────────────────────────────────────────────────

class TestPublicFeed(TestCase):
    """Public drops appear on /explore/ and are searchable."""

    def setUp(self):
        self.user = _make_user('pub_user', plan=Plan.STARTER)
        Drop.objects.create(
            ns='c', key='pub1', content='python snippet', kind='text',
            owner=self.user, is_public=True, tags='python,code',
        )
        Drop.objects.create(
            ns='c', key='priv1', content='private stuff', kind='text',
            owner=self.user, is_public=False,
        )

    def test_public_drop_in_feed(self):
        res = self.client.get('/explore/', HTTP_ACCEPT='application/json')
        self.assertEqual(res.status_code, 200)
        keys = [d['key'] for d in res.json()['drops']]
        self.assertIn('pub1', keys)

    def test_private_drop_not_in_feed(self):
        res = self.client.get('/explore/', HTTP_ACCEPT='application/json')
        keys = [d['key'] for d in res.json()['drops']]
        self.assertNotIn('priv1', keys)

    def test_search_by_tag(self):
        res = self.client.get('/explore/?tag=python', HTTP_ACCEPT='application/json')
        keys = [d['key'] for d in res.json()['drops']]
        self.assertIn('pub1', keys)

    def test_search_by_query(self):
        res = self.client.get('/explore/?q=snippet', HTTP_ACCEPT='application/json')
        keys = [d['key'] for d in res.json()['drops']]
        self.assertIn('pub1', keys)

    def test_no_results_for_unmatched_query(self):
        res = self.client.get('/explore/?q=zzz_no_match', HTTP_ACCEPT='application/json')
        self.assertEqual(res.json()['drops'], [])


# ── Feature Voting ───────────────────────────────────────────────────────────

class TestFeatureVoting(TestCase):
    """Feature voting: weight enforced, anon blocked from voting/submitting."""

    def test_anon_can_view_features(self):
        res = self.client.get('/features/')
        self.assertEqual(res.status_code, 200)

    def test_anon_cannot_submit(self):
        import json as _json
        res = self.client.post(
            '/features/submit/',
            data=_json.dumps({"title": "more storage"}),
            content_type='application/json',
        )
        self.assertEqual(res.status_code, 401)

    def test_anon_cannot_vote(self):
        from core.models import FeatureProposal
        u = _make_user('fp_owner')
        p = FeatureProposal.objects.create(title='test feat', proposed_by=u)
        res = self.client.post(f'/features/{p.pk}/vote/')
        self.assertEqual(res.status_code, 401)

    def test_free_user_can_submit(self):
        import json as _json
        u = _make_user('fp_free')
        self.client.force_login(u)
        res = self.client.post(
            '/features/submit/',
            data=_json.dumps({"title": "dark mode", "description": "please"}),
            content_type='application/json',
        )
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.json()['title'], 'dark mode')

    def test_free_vote_weight_1(self):
        from core.models import FeatureProposal, FeatureVote
        u = _make_user('fp_voter_free')
        p = FeatureProposal.objects.create(title='feat1', proposed_by=u)
        self.client.force_login(u)
        res = self.client.post(f'/features/{p.pk}/vote/')
        self.assertEqual(res.status_code, 200)
        vote = FeatureVote.objects.get(proposal=p, user=u)
        self.assertEqual(vote.weight, 1)

    def test_paid_vote_weight_3(self):
        from core.models import FeatureProposal, FeatureVote
        u = _make_user('fp_voter_paid', plan=Plan.STARTER)
        p = FeatureProposal.objects.create(title='feat2', proposed_by=u)
        self.client.force_login(u)
        self.client.post(f'/features/{p.pk}/vote/')
        vote = FeatureVote.objects.get(proposal=p, user=u)
        self.assertEqual(vote.weight, 3)

    def test_vote_toggle_removes(self):
        from core.models import FeatureProposal, FeatureVote
        u = _make_user('fp_toggler')
        p = FeatureProposal.objects.create(title='feat3', proposed_by=u)
        self.client.force_login(u)
        self.client.post(f'/features/{p.pk}/vote/')
        self.assertTrue(FeatureVote.objects.filter(proposal=p, user=u).exists())
        self.client.post(f'/features/{p.pk}/vote/')
        self.assertFalse(FeatureVote.objects.filter(proposal=p, user=u).exists())

    def test_score_reflects_votes(self):
        from core.models import FeatureProposal
        u1 = _make_user('fp_s1')
        u2 = _make_user('fp_s2', plan=Plan.PRO)
        p = FeatureProposal.objects.create(title='scored', proposed_by=u1)
        self.client.force_login(u1)
        self.client.post(f'/features/{p.pk}/vote/')
        self.client.force_login(u2)
        res = self.client.post(f'/features/{p.pk}/vote/')
        self.assertEqual(res.json()['score'], 4)  # 1 + 3
