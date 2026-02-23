"""
tests/unit/test_auth.py

Unit tests for registration and username validation.
"""

from django.contrib.auth.models import User
from django.test import TestCase

from core.views.helpers import validate_username


# ── validate_username ─────────────────────────────────────────────────────────

class TestValidateUsername(TestCase):
    def test_valid_simple(self):
        self.assertIsNone(validate_username('alice'))

    def test_valid_with_numbers(self):
        self.assertIsNone(validate_username('alice123'))

    def test_valid_with_hyphen(self):
        self.assertIsNone(validate_username('alice-bob'))

    def test_valid_with_underscore(self):
        self.assertIsNone(validate_username('alice_bob'))

    def test_valid_max_length(self):
        self.assertIsNone(validate_username('a' * 30))

    def test_empty_rejected(self):
        self.assertIsNotNone(validate_username(''))

    def test_too_long_rejected(self):
        self.assertIsNotNone(validate_username('a' * 31))

    def test_at_sign_rejected(self):
        self.assertIsNotNone(validate_username('@alice'))

    def test_space_rejected(self):
        self.assertIsNotNone(validate_username('alice bob'))

    def test_dot_rejected(self):
        self.assertIsNotNone(validate_username('alice.bob'))

    def test_uppercase_valid(self):
        # uppercase is allowed, uniqueness check is case-insensitive
        self.assertIsNone(validate_username('Alice'))


# ── Registration view ─────────────────────────────────────────────────────────

def _register(client, username='alice', email='alice@test.com',
              password='password123', password2=None, plan='free'):
    return client.post('/auth/register/', {
        'username': username,
        'email': email,
        'password': password,
        'password2': password2 if password2 is not None else password,
        'plan': plan,
    }, follow=True)


class TestRegistrationView(TestCase):
    def test_successful_registration(self):
        res = _register(self.client)
        self.assertEqual(res.status_code, 200)
        self.assertTrue(User.objects.filter(username='alice').exists())

    def test_username_stored_not_email(self):
        _register(self.client)
        user = User.objects.get(username='alice')
        self.assertEqual(user.email, 'alice@test.com')
        self.assertEqual(user.username, 'alice')

    def test_duplicate_username_rejected(self):
        _register(self.client, username='alice', email='alice@test.com')
        res = _register(self.client, username='alice', email='other@test.com')
        self.assertFalse(User.objects.filter(email='other@test.com').exists())
        self.assertContains(res, 'taken')

    def test_username_uniqueness_is_case_insensitive(self):
        _register(self.client, username='Alice', email='alice@test.com')
        res = _register(self.client, username='alice', email='other@test.com')
        self.assertFalse(User.objects.filter(email='other@test.com').exists())

    def test_invalid_username_rejected(self):
        res = _register(self.client, username='bad username!')
        self.assertFalse(User.objects.filter(email='alice@test.com').exists())
        self.assertContains(res, 'Username')

    def test_missing_username_rejected(self):
        res = _register(self.client, username='')
        self.assertFalse(User.objects.filter(email='alice@test.com').exists())

    def test_password_mismatch_rejected(self):
        res = _register(self.client, password2='different123')
        self.assertFalse(User.objects.filter(username='alice').exists())

    def test_duplicate_email_rejected(self):
        _register(self.client, username='alice', email='shared@test.com')
        res = _register(self.client, username='bob', email='shared@test.com')
        self.assertFalse(User.objects.filter(username='bob').exists())


# ── Login view ────────────────────────────────────────────────────────────────

class TestLoginView(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='alice', email='alice@test.com', password='password123',
        )

    def test_login_with_username(self):
        res = self.client.post('/auth/login/', {
            'email': 'alice', 'password': 'password123',
        })
        self.assertEqual(res.status_code, 302)

    def test_login_with_email(self):
        res = self.client.post('/auth/login/', {
            'email': 'alice@test.com', 'password': 'password123',
        })
        self.assertEqual(res.status_code, 302)

    def test_login_with_email_case_insensitive(self):
        res = self.client.post('/auth/login/', {
            'email': 'Alice@Test.COM', 'password': 'password123',
        })
        self.assertEqual(res.status_code, 302)

    def test_wrong_password_rejected(self):
        res = self.client.post('/auth/login/', {
            'email': 'alice', 'password': 'wrong',
        })
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Invalid')


# ── Key @ restriction ─────────────────────────────────────────────────────────

class TestAtKeyRestriction(TestCase):
    def test_key_starting_with_at_rejected(self):
        res = self.client.post('/save/', {
            'key': '@alice',
            'content': 'hello',
        }, HTTP_ACCEPT='application/json')
        self.assertEqual(res.status_code, 400)
        self.assertIn('error', res.json())

    def test_normal_key_accepted(self):
        res = self.client.post('/save/', {
            'key': 'alice',
            'content': 'hello',
        }, HTTP_ACCEPT='application/json')
        self.assertEqual(res.status_code, 200)

    def test_check_key_at_returns_unavailable(self):
        res = self.client.get('/check-key/', {'key': '@alice', 'ns': 'c'})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertFalse(data['available'])
        self.assertTrue(data.get('reserved'))
