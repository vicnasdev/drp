"""
Integration tests: API token CRUD.

POST /auth/tokens/create/            — create token (paid only)
GET  /auth/tokens/                   — list tokens
POST /auth/tokens/<id>/revoke/       — revoke token
"""

import json
import pytest

from core.models import APIToken, Plan, UserProfile

pytestmark = pytest.mark.django_db


class TestCreateToken:
    """POST /auth/tokens/create/"""

    def test_paid_user_creates_token(self, client, fake_b2, starter_user):
        client.force_login(starter_user)
        resp = client.post(
            "/auth/tokens/create/",
            data=json.dumps({"label": "CI deploy"}),
            content_type="application/json",
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "token" in data
        assert data["prefix"]  # 8-char prefix
        assert data["label"] == "CI deploy"
        assert APIToken.objects.filter(user=starter_user).count() == 1

    def test_free_user_rejected(self, client, fake_b2, free_user):
        client.force_login(free_user)
        resp = client.post(
            "/auth/tokens/create/",
            data=json.dumps({"label": "nope"}),
            content_type="application/json",
        )
        assert resp.status_code == 403

    def test_anon_rejected(self, client, fake_b2):
        resp = client.post(
            "/auth/tokens/create/",
            data=json.dumps({"label": "anon"}),
            content_type="application/json",
        )
        assert resp.status_code == 401

    def test_token_with_expiry(self, client, fake_b2, starter_user):
        client.force_login(starter_user)
        resp = client.post(
            "/auth/tokens/create/",
            data=json.dumps({"label": "temp", "expires": "30d"}),
            content_type="application/json",
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["expires_at"] is not None

    def test_token_without_expiry(self, client, fake_b2, starter_user):
        client.force_login(starter_user)
        resp = client.post(
            "/auth/tokens/create/",
            data=json.dumps({"label": "forever"}),
            content_type="application/json",
        )
        assert resp.status_code == 201
        assert resp.json()["expires_at"] is None

    def test_token_shown_only_once(self, client, fake_b2, starter_user):
        """The raw token is only in the create response. List doesn't expose it."""
        client.force_login(starter_user)
        resp = client.post(
            "/auth/tokens/create/",
            data=json.dumps({"label": "once"}),
            content_type="application/json",
        )
        raw_token = resp.json()["token"]
        assert len(raw_token) > 20

        # List should not include the raw token
        resp = client.get("/auth/tokens/")
        tokens = resp.json()["tokens"]
        assert len(tokens) == 1
        assert "token" not in tokens[0]  # raw token not exposed


class TestListTokens:
    """GET /auth/tokens/"""

    def test_list_empty(self, client, fake_b2, starter_user):
        client.force_login(starter_user)
        resp = client.get("/auth/tokens/")
        assert resp.status_code == 200
        assert resp.json()["tokens"] == []

    def test_list_shows_metadata(self, client, fake_b2, starter_user):
        client.force_login(starter_user)
        client.post(
            "/auth/tokens/create/",
            data=json.dumps({"label": "my-key"}),
            content_type="application/json",
        )

        resp = client.get("/auth/tokens/")
        tokens = resp.json()["tokens"]
        assert len(tokens) == 1
        t = tokens[0]
        assert t["label"] == "my-key"
        assert "prefix" in t
        assert "created_at" in t
        assert t["expired"] is False

    def test_list_requires_login(self, client, fake_b2):
        resp = client.get("/auth/tokens/")
        assert resp.status_code == 401


class TestRevokeToken:
    """POST /auth/tokens/<id>/revoke/"""

    def test_revoke_own_token(self, client, fake_b2, starter_user):
        client.force_login(starter_user)
        resp = client.post(
            "/auth/tokens/create/",
            data=json.dumps({"label": "revokable"}),
            content_type="application/json",
        )
        # Get the token ID from the list
        resp = client.get("/auth/tokens/")
        token_id = resp.json()["tokens"][0]["id"]

        resp = client.post(f"/auth/tokens/{token_id}/revoke/")
        assert resp.status_code == 200
        assert APIToken.objects.filter(user=starter_user).count() == 0

    def test_revoke_nonexistent(self, client, fake_b2, starter_user):
        client.force_login(starter_user)
        resp = client.post("/auth/tokens/99999/revoke/")
        assert resp.status_code == 404

    def test_cannot_revoke_others_token(self, client, fake_b2, starter_user, pro_user):
        client.force_login(starter_user)
        client.post(
            "/auth/tokens/create/",
            data=json.dumps({"label": "starter-key"}),
            content_type="application/json",
        )
        resp = client.get("/auth/tokens/")
        token_id = resp.json()["tokens"][0]["id"]

        client.force_login(pro_user)
        resp = client.post(f"/auth/tokens/{token_id}/revoke/")
        assert resp.status_code == 404  # not found for this user
        # Token still exists
        assert APIToken.objects.filter(pk=token_id).exists()
