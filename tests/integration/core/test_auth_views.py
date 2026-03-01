"""Integration tests for auth views — login, register, logout, account, email verify."""

import pytest
from django.contrib.auth.models import User
from django.core.signing import TimestampSigner
from django.test import Client

from core.models import Plan, UserProfile


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def user(db):
    u = User.objects.create_user(username="alice", email="alice@example.com", password="pass1234")
    UserProfile.objects.create(user=u, plan=Plan.FREE)
    return u


@pytest.fixture
def client():
    return Client()


# ── Login ────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestLogin:

    def test_login_page_renders(self, client):
        resp = client.get("/auth/login/")
        assert resp.status_code == 200
        assert b"log in" in resp.content.lower()

    def test_login_with_username(self, client, user):
        resp = client.post("/auth/login/", {
            "email": "alice", "password": "pass1234",
        })
        assert resp.status_code == 302

    def test_login_with_email(self, client, user):
        resp = client.post("/auth/login/", {
            "email": "alice@example.com", "password": "pass1234",
        })
        assert resp.status_code == 302

    def test_login_bad_credentials(self, client, user):
        resp = client.post("/auth/login/", {
            "email": "alice", "password": "wrong",
        })
        assert resp.status_code == 200
        assert b"invalid" in resp.content.lower()

    def test_already_logged_in_redirects(self, client, user):
        client.login(username="alice", password="pass1234")
        resp = client.get("/auth/login/")
        assert resp.status_code == 302


# ── Register ─────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestRegister:

    def test_register_page_renders(self, client):
        resp = client.get("/auth/register/")
        assert resp.status_code == 200
        assert b"create account" in resp.content.lower()

    def test_register_creates_user(self, client, db):
        resp = client.post("/auth/register/", {
            "username": "newuser",
            "email": "new@example.com",
            "password": "strongpass",
            "password2": "strongpass",
            "plan": "free",
        })
        assert resp.status_code == 302
        assert User.objects.filter(username="newuser").exists()
        assert UserProfile.objects.filter(user__username="newuser").exists()

    def test_register_password_mismatch(self, client, db):
        resp = client.post("/auth/register/", {
            "username": "newuser",
            "email": "new@example.com",
            "password": "strongpass",
            "password2": "different",
            "plan": "free",
        })
        assert resp.status_code == 200
        assert b"do not match" in resp.content.lower()

    def test_register_duplicate_username(self, client, user):
        resp = client.post("/auth/register/", {
            "username": "alice",
            "email": "other@example.com",
            "password": "strongpass",
            "password2": "strongpass",
            "plan": "free",
        })
        assert resp.status_code == 200
        assert b"taken" in resp.content.lower()

    def test_register_duplicate_email(self, client, user):
        resp = client.post("/auth/register/", {
            "username": "newuser",
            "email": "alice@example.com",
            "password": "strongpass",
            "password2": "strongpass",
            "plan": "free",
        })
        assert resp.status_code == 200
        assert b"already exists" in resp.content.lower()


# ── Logout ───────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestLogout:

    def test_logout_clears_session(self, client, user):
        client.login(username="alice", password="pass1234")
        resp = client.get("/auth/logout/")
        assert resp.status_code == 302
        # Subsequent protected page should redirect
        resp = client.get("/auth/account/")
        assert resp.status_code == 302


# ── Account ──────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestAccount:

    def test_account_requires_login(self, client):
        resp = client.get("/auth/account/")
        assert resp.status_code == 302
        assert "/auth/login/" in resp.url

    def test_account_renders(self, client, user):
        client.login(username="alice", password="pass1234")
        resp = client.get("/auth/account/")
        assert resp.status_code == 200
        assert b"account" in resp.content.lower()


# ── Account settings ────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestAccountSettings:

    def test_save_notification_prefs(self, client, user):
        client.login(username="alice", password="pass1234")
        resp = client.post("/auth/account/settings/", {
            "notify_product_updates": "1",
            # notify_billing omitted → should be False
            "notify_bug_fix": "1",
        })
        assert resp.status_code == 302
        profile = UserProfile.objects.get(user=user)
        assert profile.notify_product_updates is True
        assert profile.notify_billing is False
        assert profile.notify_bug_fix is True


# ── Email verification ──────────────────────────────────────────────────────

@pytest.mark.django_db
class TestEmailVerify:

    def _make_token(self, user):
        signer = TimestampSigner(salt="email-verify")
        return signer.sign(str(user.pk))

    def test_valid_token_verifies(self, client, user):
        token = self._make_token(user)
        resp = client.get(f"/auth/verify/{token}/")
        assert resp.status_code == 200
        assert b"verified" in resp.content.lower()
        user.profile.refresh_from_db()
        assert user.profile.email_verified is True

    def test_invalid_token(self, client, user):
        resp = client.get("/auth/verify/garbage:token/")
        assert resp.status_code == 200
        assert b"invalid" in resp.content.lower()

    def test_verify_resend_requires_login(self, client):
        resp = client.post("/auth/verify-resend/")
        assert resp.status_code == 302

    def test_verify_resend_sends(self, client, user):
        client.login(username="alice", password="pass1234")
        resp = client.post("/auth/verify-resend/")
        assert resp.status_code == 200
        assert b"sent" in resp.content.lower()
