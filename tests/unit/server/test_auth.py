"""
Tests for auth registration, username validation, and key validation.

Covers validate_username, is_valid_drop_key, invalid_key_message,
and the registration view.
"""

import pytest
from django.test import TestCase, Client, override_settings
from django.contrib.auth.models import User

_SIMPLE_STATIC = {"staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}}

from core.views.helpers import validate_username, is_valid_drop_key, invalid_key_message


# ── validate_username ────────────────────────────────────────────────────────

class TestValidateUsername:
    def test_valid_simple(self):
        assert validate_username('alice') is None

    def test_valid_with_numbers(self):
        assert validate_username('user42') is None

    def test_valid_with_hyphen(self):
        assert validate_username('my-user') is None

    def test_valid_with_underscore(self):
        assert validate_username('my_user') is None

    def test_valid_max_length(self):
        assert validate_username('a' * 30) is None

    def test_empty_rejected(self):
        assert validate_username('') is not None

    def test_too_long_rejected(self):
        assert validate_username('a' * 31) is not None

    def test_at_sign_rejected(self):
        assert validate_username('@alice') is not None

    def test_space_rejected(self):
        assert validate_username('my user') is not None

    def test_dot_rejected(self):
        assert validate_username('my.user') is not None

    def test_uppercase_valid(self):
        assert validate_username('Alice') is None


# ── is_valid_drop_key ────────────────────────────────────────────────────────

class TestIsValidDropKey:
    def test_normal_key(self):
        assert is_valid_drop_key('hello') is True

    def test_key_with_numbers(self):
        assert is_valid_drop_key('report2024') is True

    def test_key_with_hyphens(self):
        assert is_valid_drop_key('my-file') is True

    def test_empty_rejected(self):
        assert is_valid_drop_key('') is False

    def test_at_prefix_rejected(self):
        assert is_valid_drop_key('@alice') is False

    def test_hash_rejected(self):
        assert is_valid_drop_key('my#key') is False

    def test_question_mark_rejected(self):
        assert is_valid_drop_key('my?key') is False

    def test_slash_rejected(self):
        assert is_valid_drop_key('my/key') is False

    def test_space_rejected(self):
        assert is_valid_drop_key('my key') is False

    def test_percent_rejected(self):
        assert is_valid_drop_key('my%key') is False


# ── invalid_key_message ──────────────────────────────────────────────────────

class TestInvalidKeyMessage:
    def test_valid_key_returns_none(self):
        assert invalid_key_message('hello') is None

    def test_empty_key_message(self):
        msg = invalid_key_message('')
        assert msg is not None
        assert 'empty' in msg.lower()

    def test_at_key_message(self):
        msg = invalid_key_message('@alice')
        assert msg is not None
        assert '@' in msg

    def test_bad_chars_listed(self):
        msg = invalid_key_message('my#key')
        assert '#' in msg
_DUMMY_CACHE = {"default": {"BACKEND": "django.core.cache.backends.dummy.DummyCache"}}


# ── Registration view ────────────────────────────────────────────────────────

@pytest.mark.django_db
@override_settings(STORAGES=_SIMPLE_STATIC, CACHES=_DUMMY_CACHE)
class TestRegistrationView(TestCase):
    def setUp(self):
        self.client = Client()

    def test_successful_registration(self):
        resp = self.client.post('/auth/register/', {
            'email': 'test@test.com', 'username': 'testuser',
            'password': 'testpass123', 'password2': 'testpass123',
        })
        assert resp.status_code in (200, 302)

    def test_username_stored(self):
        self.client.post('/auth/register/', {
            'email': 'u@t.com', 'username': 'myuser',
            'password': 'testpass123', 'password2': 'testpass123',
        })
        assert User.objects.filter(username='myuser').exists()

    def test_duplicate_username_rejected(self):
        User.objects.create_user('taken', 'a@b.com', 'pw12345678')
        resp = self.client.post('/auth/register/', {
            'email': 'new@t.com', 'username': 'taken',
            'password': 'testpass123', 'password2': 'testpass123',
        })
        assert resp.status_code == 200  # re-renders form with error
        assert b'already taken' in resp.content.lower()

    def test_username_uniqueness_case_insensitive(self):
        User.objects.create_user('Alice', 'a@b.com', 'pw12345678')
        resp = self.client.post('/auth/register/', {
            'email': 'new@t.com', 'username': 'alice',
            'password': 'testpass123', 'password2': 'testpass123',
        })
        assert resp.status_code == 200

    def test_password_mismatch_rejected(self):
        resp = self.client.post('/auth/register/', {
            'email': 'x@t.com', 'username': 'user1',
            'password': 'testpass123', 'password2': 'different',
        })
        assert resp.status_code == 200
        assert b'match' in resp.content.lower()

    def test_invalid_username_rejected(self):
        resp = self.client.post('/auth/register/', {
            'email': 'x@t.com', 'username': '@bad',
            'password': 'testpass123', 'password2': 'testpass123',
        })
        assert resp.status_code == 200

    def test_short_password_rejected(self):
        resp = self.client.post('/auth/register/', {
            'email': 'x@t.com', 'username': 'short',
            'password': 'abc', 'password2': 'abc',
        })
        assert resp.status_code == 200
        assert b'8 characters' in resp.content.lower()


# ── At-key restriction on drops ──────────────────────────────────────────────

@pytest.mark.django_db
@override_settings(STORAGES=_SIMPLE_STATIC)
class TestAtKeyRestriction(TestCase):
    def setUp(self):
        self.client = Client()

    def test_key_starting_with_at_rejected(self):
        resp = self.client.post('/save/', {
            'content': 'test',
            'key': '@stolen',
        })
        assert resp.status_code == 400

    def test_normal_key_accepted(self):
        resp = self.client.post('/save/', {
            'content': 'hello world',
            'key': 'normalkey',
        })
        assert resp.status_code == 200
