"""
Integration tests: drop ownership transfer via one-time tokens.

POST /<key>/send/     — generate a transfer token (owner only)
POST /claim/<token>/  — claim ownership with a transfer token
"""

import json
import pytest
from datetime import timedelta
from django.utils import timezone

from core.models import Drop, TransferToken

pytestmark = pytest.mark.django_db


class TestSendTransfer:
    """POST /<key>/send/ — owner generates a transfer token."""

    def test_send_creates_token(self, client, fake_b2, starter_user):
        client.force_login(starter_user)
        client.post("/save/", {"content": "gift", "key": "tr-s1"})

        resp = client.post("/tr-s1/send/")
        assert resp.status_code == 200
        data = resp.json()
        assert "token" in data
        assert data["key"] == "tr-s1"
        assert data["kind"] == "text"
        assert TransferToken.objects.filter(drop__key="tr-s1").exists()

    def test_send_requires_login(self, client, fake_b2):
        client.post("/save/", {"content": "anon", "key": "tr-s2"})
        resp = client.post("/tr-s2/send/")
        assert resp.status_code == 401

    def test_send_requires_ownership(self, client, fake_b2, starter_user, free_user):
        client.force_login(starter_user)
        client.post("/save/", {"content": "mine", "key": "tr-s3"})
        client.force_login(free_user)
        resp = client.post("/tr-s3/send/")
        assert resp.status_code == 404

    def test_send_nonexistent_drop(self, client, fake_b2, free_user):
        client.force_login(free_user)
        resp = client.post("/ghost-drop/send/")
        assert resp.status_code == 404

    def test_send_revokes_previous_pending(self, client, fake_b2, starter_user):
        client.force_login(starter_user)
        client.post("/save/", {"content": "multi", "key": "tr-s4"})

        resp1 = client.post("/tr-s4/send/")
        token1 = resp1.json()["token"]

        resp2 = client.post("/tr-s4/send/")
        token2 = resp2.json()["token"]

        assert token1 != token2
        # First token should now be expired
        tt1 = TransferToken.objects.get(token=token1)
        assert not tt1.is_valid()
        # Second token should be valid
        tt2 = TransferToken.objects.get(token=token2)
        assert tt2.is_valid()

    def test_send_requires_post(self, client, fake_b2, starter_user):
        client.force_login(starter_user)
        client.post("/save/", {"content": "x", "key": "tr-s5"})
        resp = client.get("/tr-s5/send/")
        assert resp.status_code == 405


class TestClaimTransfer:
    """POST /claim/<token>/ — recipient claims ownership."""

    def test_claim_transfers_ownership(self, client, fake_b2, starter_user, free_user):
        client.force_login(starter_user)
        client.post("/save/", {"content": "transferable", "key": "tr-c1"})
        resp = client.post("/tr-c1/send/")
        token = resp.json()["token"]

        client.force_login(free_user)
        resp = client.post(f"/claim/{token}/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["key"] == "tr-c1"
        assert data["from"] == "starter"

        drop = Drop.objects.get(key="tr-c1")
        assert drop.owner == free_user

    def test_claim_requires_login(self, client, fake_b2, starter_user):
        client.force_login(starter_user)
        client.post("/save/", {"content": "x", "key": "tr-c2"})
        resp = client.post("/tr-c2/send/")
        token = resp.json()["token"]

        client.logout()
        resp = client.post(f"/claim/{token}/")
        assert resp.status_code == 401

    def test_claim_invalid_token(self, client, fake_b2, free_user):
        client.force_login(free_user)
        resp = client.post("/claim/bogus-token-value/")
        assert resp.status_code == 404

    def test_cannot_transfer_to_self(self, client, fake_b2, starter_user):
        client.force_login(starter_user)
        client.post("/save/", {"content": "self", "key": "tr-c3"})
        resp = client.post("/tr-c3/send/")
        token = resp.json()["token"]

        resp = client.post(f"/claim/{token}/")
        assert resp.status_code == 400
        assert "yourself" in resp.json()["error"].lower()

    def test_claim_expired_token(self, client, fake_b2, starter_user, free_user):
        client.force_login(starter_user)
        client.post("/save/", {"content": "old", "key": "tr-c4"})
        resp = client.post("/tr-c4/send/")
        token = resp.json()["token"]

        # Expire the token
        tt = TransferToken.objects.get(token=token)
        tt.expires_at = timezone.now() - timedelta(hours=1)
        tt.save(update_fields=["expires_at"])

        client.force_login(free_user)
        resp = client.post(f"/claim/{token}/")
        assert resp.status_code == 410

    def test_claim_already_claimed_token(self, client, fake_b2, starter_user, free_user, pro_user):
        client.force_login(starter_user)
        client.post("/save/", {"content": "once", "key": "tr-c5"})
        resp = client.post("/tr-c5/send/")
        token = resp.json()["token"]

        # First claim
        client.force_login(free_user)
        resp = client.post(f"/claim/{token}/")
        assert resp.status_code == 200

        # Second claim attempt
        client.force_login(pro_user)
        resp = client.post(f"/claim/{token}/")
        assert resp.status_code == 410
