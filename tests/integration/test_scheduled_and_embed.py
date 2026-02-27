"""
Integration tests: scheduled drops and embed view.

Covers:
  - Scheduled drops (visible_from) — hidden until time
  - GET /embed/<key>/ — minimal iframe view
"""

import pytest
from datetime import timedelta
from django.utils import timezone

from core.models import Drop

pytestmark = pytest.mark.django_db


class TestScheduledDrops:
    """Drops with visible_from set are hidden until that time."""

    def test_scheduled_drop_hidden_from_non_owner(self, client, fake_b2, starter_user, free_user):
        client.force_login(starter_user)
        client.post("/save/", {
            "content": "future",
            "key": "sched-1",
            "schedule": "24h",
        })
        drop = Drop.objects.get(key="sched-1")
        assert drop.visible_from is not None

        # Non-owner can't see it
        client.force_login(free_user)
        resp = client.get("/sched-1/", HTTP_ACCEPT="application/json")
        assert resp.status_code == 403

    def test_scheduled_drop_visible_to_owner(self, client, fake_b2, starter_user):
        client.force_login(starter_user)
        client.post("/save/", {
            "content": "my scheduled",
            "key": "sched-2",
            "schedule": "1h",
        })

        # Owner can still see it
        resp = client.get("/sched-2/", HTTP_ACCEPT="application/json")
        assert resp.status_code == 200
        assert resp.json()["content"] == "my scheduled"

    def test_scheduled_drop_becomes_visible(self, client, fake_b2, starter_user, free_user):
        client.force_login(starter_user)
        client.post("/save/", {
            "content": "now visible",
            "key": "sched-3",
            "schedule": "1h",
        })

        # Move visible_from to the past
        drop = Drop.objects.get(key="sched-3")
        drop.visible_from = timezone.now() - timedelta(minutes=1)
        drop.save(update_fields=["visible_from"])

        # Now anyone can see it
        client.force_login(free_user)
        resp = client.get("/sched-3/", HTTP_ACCEPT="application/json")
        assert resp.status_code == 200
        assert resp.json()["content"] == "now visible"

    def test_free_user_schedule_ignored(self, client, fake_b2, free_user):
        """Free users can't schedule — schedule param is ignored."""
        client.force_login(free_user)
        client.post("/save/", {
            "content": "free schedule",
            "key": "sched-4",
            "schedule": "24h",
        })
        drop = Drop.objects.get(key="sched-4")
        assert drop.visible_from is None


class TestEmbedView:
    """GET /embed/<key>/ — minimal iframe embed."""

    def test_embed_text_drop(self, client, fake_b2):
        client.post("/save/", {"content": "embedded text", "key": "emb-1"})
        resp = client.get("/embed/emb-1/")
        assert resp.status_code == 200
        assert b"embedded text" in resp.content

    def test_embed_nonexistent_returns_404(self, client, fake_b2):
        resp = client.get("/embed/nonexistent/")
        assert resp.status_code == 404

    def test_embed_password_protected_returns_401(self, client, fake_b2, starter_user):
        client.force_login(starter_user)
        client.post("/save/", {
            "content": "secret embed",
            "key": "emb-2",
            "password": "pass123",
        })
        client.logout()

        resp = client.get("/embed/emb-2/")
        assert resp.status_code == 401

    def test_embed_expired_returns_410(self, client, fake_b2):
        client.post("/save/", {"content": "old", "key": "emb-3"})
        drop = Drop.objects.get(key="emb-3")
        drop.expires_at = timezone.now() - timedelta(hours=1)
        drop.save(update_fields=["expires_at"])

        resp = client.get("/embed/emb-3/")
        assert resp.status_code == 410

    def test_embed_scheduled_returns_403(self, client, fake_b2, starter_user):
        client.force_login(starter_user)
        client.post("/save/", {
            "content": "pending",
            "key": "emb-4",
            "schedule": "24h",
        })
        client.logout()

        resp = client.get("/embed/emb-4/")
        assert resp.status_code == 403

    def test_embed_file_drop(self, client, fake_b2):
        from django.core.files.uploadedfile import SimpleUploadedFile
        f = SimpleUploadedFile("pic.png", b"\x89PNG", content_type="image/png")
        client.post("/save/", {"file": f, "key": "emb-5"})

        resp = client.get("/embed/emb-5/")
        assert resp.status_code == 200
