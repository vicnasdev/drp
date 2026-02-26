"""
tests/unit/test_auth.py

Unit tests for registration, username validation, manage page, and account page.
"""

import json
from django.contrib.auth.models import User
from django.test import TestCase

from core.models import Drop, Plan, UserProfile, Collection, EmailTemplate
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


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_user(username='testuser', plan=Plan.FREE, password='pw12345678'):
    u = User.objects.create_user(username, email=f'{username}@test.com', password=password)
    UserProfile.objects.filter(user=u).update(plan=plan, email_verified=True)
    u.refresh_from_db()
    return u


# ── Manage page ───────────────────────────────────────────────────────────────

class TestManagePage(TestCase):
    def setUp(self):
        self.user = _make_user()
        self.client.login(username='testuser', password='pw12345678')

    def test_manage_page_loads(self):
        res = self.client.get('/auth/manage/')
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'manage')

    def test_manage_page_requires_login(self):
        self.client.logout()
        res = self.client.get('/auth/manage/')
        self.assertEqual(res.status_code, 302)
        self.assertIn('/auth/login/', res.url)

    def test_manage_shows_drops(self):
        Drop.objects.create(ns='c', key='testdrop', kind='text', content='hello', owner=self.user)
        res = self.client.get('/auth/manage/')
        self.assertContains(res, 'testdrop')

    def test_manage_shows_select_all_checkbox(self):
        Drop.objects.create(ns='c', key='testdrop', kind='text', content='hi', owner=self.user)
        res = self.client.get('/auth/manage/')
        self.assertContains(res, 'select-all')

    def test_manage_shows_collections(self):
        Collection.objects.create(name='mybox', slug='mybox', owner=self.user)
        res = self.client.get('/auth/manage/')
        self.assertContains(res, 'mybox')

    def test_manage_bulk_delete_button_present(self):
        Drop.objects.create(ns='c', key='td1', kind='text', content='x', owner=self.user)
        res = self.client.get('/auth/manage/')
        self.assertContains(res, 'bulkDelete')


# ── Account page (cleaned) ───────────────────────────────────────────────────

class TestAccountPageCleaned(TestCase):
    def setUp(self):
        self.user = _make_user()
        self.client.login(username='testuser', password='pw12345678')

    def test_account_no_drops_table(self):
        """Account page should not list individual drops anymore."""
        Drop.objects.create(ns='c', key='mydrop', kind='text', content='x', owner=self.user)
        res = self.client.get('/auth/account/')
        self.assertNotContains(res, 'drops-table')

    def test_account_has_manage_link(self):
        res = self.client.get('/auth/account/')
        self.assertContains(res, '/auth/manage/')

    def test_account_has_ad_slot(self):
        res = self.client.get('/auth/account/')
        # The ads/middle.html include should render (even without adsense_client)
        self.assertContains(res, 'koho')  # Koho fallback always present

    def test_account_still_has_notifications(self):
        res = self.client.get('/auth/account/')
        self.assertContains(res, 'notifications')

    def test_account_still_has_plan_section(self):
        res = self.client.get('/auth/account/')
        self.assertContains(res, 'plan')


# ── EmailTemplate model ──────────────────────────────────────────────────────

class TestEmailTemplate(TestCase):
    def test_create_and_get(self):
        EmailTemplate.objects.create(
            slug='test_tpl',
            subject='Hello {name}',
            body_text='Hi {name}, welcome.',
        )
        tpl = EmailTemplate.get('test_tpl')
        self.assertIsNotNone(tpl)
        self.assertEqual(tpl.slug, 'test_tpl')

    def test_get_nonexistent_returns_none(self):
        self.assertIsNone(EmailTemplate.get('no_such_template'))

    def test_render_subject(self):
        tpl = EmailTemplate.objects.create(
            slug='sub_test', subject='Hi {user}', body_text='body',
        )
        self.assertEqual(tpl.render_subject(user='alice'), 'Hi alice')

    def test_render_text(self):
        tpl = EmailTemplate.objects.create(
            slug='txt_test', subject='s', body_text='Hello {name}!',
        )
        self.assertEqual(tpl.render_text(name='Bob'), 'Hello Bob!')

    def test_render_html_empty(self):
        tpl = EmailTemplate.objects.create(
            slug='no_html', subject='s', body_text='body',
        )
        self.assertEqual(tpl.render_html(), '')

    def test_render_html(self):
        tpl = EmailTemplate.objects.create(
            slug='html_test', subject='s', body_text='t',
            body_html='<b>{msg}</b>',
        )
        self.assertEqual(tpl.render_html(msg='hi'), '<b>hi</b>')

    def test_get_from_email_default(self):
        from django.conf import settings
        tpl = EmailTemplate.objects.create(slug='def_from', subject='s', body_text='b')
        self.assertEqual(tpl.get_from_email(), settings.DEFAULT_FROM_EMAIL)

    def test_get_from_email_override(self):
        tpl = EmailTemplate.objects.create(
            slug='cust_from', subject='s', body_text='b',
            from_email='custom@example.com',
        )
        self.assertEqual(tpl.get_from_email(), 'custom@example.com')

    def test_slug_unique(self):
        EmailTemplate.objects.create(slug='unique1', subject='s', body_text='b')
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            EmailTemplate.objects.create(slug='unique1', subject='s2', body_text='b2')
