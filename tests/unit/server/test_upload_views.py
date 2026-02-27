"""
Tests for text upload via the save_drop endpoint.

Covers basic upload, expiry, password gating, burn flag, locking.
"""

import pytest
from django.test import TestCase, Client, override_settings
from django.contrib.auth.models import User

from core.models import Drop, Plan, UserProfile

pytestmark = pytest.mark.django_db

_SIMPLE_STATIC = {"staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}}


@override_settings(STORAGES=_SIMPLE_STATIC)
class _Base(TestCase):
    """Shared setup — create users at various plan levels."""

    def setUp(self):
        self.client = Client()
        self.free_user = User.objects.create_user('free', 'f@t.com', 'pw12345678')
        self.starter_user = User.objects.create_user('starter', 's@t.com', 'pw12345678')
        self.pro_user = User.objects.create_user('pro', 'p@t.com', 'pw12345678')
        UserProfile.objects.filter(user=self.starter_user).update(plan=Plan.STARTER)
        UserProfile.objects.filter(user=self.pro_user).update(plan=Plan.PRO)

    def _post(self, data, user=None):
        if user:
            self.client.force_login(user)
        return self.client.post('/save/', data)


# ── Basic upload ──────────────────────────────────────────────────────────────

class TestTextUploadBasic(_Base):
    def test_anon_can_upload_text(self):
        resp = self._post({'content': 'hello', 'key': 'anon1'})
        assert resp.status_code == 200
        assert Drop.objects.filter(key='anon1').exists()

    def test_free_can_upload_text(self):
        resp = self._post({'content': 'hello', 'key': 'free1'}, self.free_user)
        assert resp.status_code == 200

    def test_starter_can_upload_text(self):
        resp = self._post({'content': 'hello', 'key': 'starter1'}, self.starter_user)
        assert resp.status_code == 200

    def test_burn_flag_set(self):
        self._post({'content': 'x', 'key': 'burn1', 'burn': '1'})
        d = Drop.objects.get(key='burn1')
        assert d.burn is True

    def test_is_test_drops_get_short_expiry(self):
        self._post({'content': 'x', 'key': 'test1', 'is_test': '1'})
        d = Drop.objects.get(key='test1')
        assert d.expires_at is not None  # is_test forces a 1-hour expiry

    def test_overwrite_existing_text(self):
        self._post({'content': 'v1', 'key': 'ow1'})
        self._post({'content': 'v2', 'key': 'ow1'})
        d = Drop.objects.get(key='ow1')
        assert d.content == 'v2'


# ── Password protection ──────────────────────────────────────────────────────

class TestPasswordProtection(_Base):
    def test_password_ignored_for_free(self):
        resp = self._post({
            'content': 'x', 'key': 'pwf1', 'password': 'secret',
        }, self.free_user)
        assert resp.status_code == 200
        d = Drop.objects.get(key='pwf1')
        assert not d.is_password_protected

    def test_password_applied_for_paid(self):
        resp = self._post({
            'content': 'x', 'key': 'pwp1', 'password': 'secret',
        }, self.starter_user)
        assert resp.status_code == 200
        d = Drop.objects.get(key='pwp1')
        assert d.is_password_protected

    def test_password_applied_for_pro(self):
        self._post({
            'content': 'x', 'key': 'pwpro', 'password': 'secret',
        }, self.pro_user)
        d = Drop.objects.get(key='pwpro')
        assert d.is_password_protected


# ── Drop locking ──────────────────────────────────────────────────────────────

class TestDropLocking(_Base):
    def test_paid_drop_is_locked(self):
        self._post({'content': 'x', 'key': 'lk1'}, self.starter_user)
        d = Drop.objects.get(key='lk1')
        assert d.locked is True

    def test_free_drop_not_permanently_locked(self):
        self._post({'content': 'x', 'key': 'lk2'}, self.free_user)
        d = Drop.objects.get(key='lk2')
        assert d.locked is False

    def test_other_user_cannot_overwrite_paid(self):
        self._post({'content': 'original', 'key': 'lk3'}, self.starter_user)
        self.client.force_login(self.pro_user)
        resp = self._post({'content': 'stolen', 'key': 'lk3'}, self.pro_user)
        d = Drop.objects.get(key='lk3')
        assert d.content == 'original'


# ── Text size limits ─────────────────────────────────────────────────────────

class TestTextSizeLimits(_Base):
    def test_text_over_free_limit_rejected(self):
        huge = 'x' * (500 * 1024 + 1)
        resp = self._post({'content': huge, 'key': 'big1'}, self.free_user)
        assert resp.status_code == 400

    def test_text_within_free_limit_accepted(self):
        ok_text = 'x' * (500 * 1024 - 100)
        resp = self._post({'content': ok_text, 'key': 'oksize'}, self.free_user)
        assert resp.status_code == 200


# ── Key validation ────────────────────────────────────────────────────────────

class TestKeyValidation(_Base):
    def test_at_key_rejected(self):
        resp = self._post({'content': 'x', 'key': '@alice'}, self.free_user)
        if resp.status_code == 200:
            data = resp.json()
            assert not data.get('ok', True)

    def test_check_key_available(self):
        resp = self.client.get('/check-key/', {'key': 'freshkey99'})
        assert resp.status_code == 200
        assert resp.json()['available'] is True

    def test_check_key_taken(self):
        self._post({'content': 'x', 'key': 'taken99'})
        resp = self.client.get('/check-key/', {'key': 'taken99'})
        assert resp.status_code == 200
        assert resp.json()['available'] is False
