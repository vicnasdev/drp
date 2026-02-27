"""
Integration tests: public drops, explore feed, and likes.

Covers:
  - Public drop creation (is_public flag)
  - GET /explore/ — public feed search/filter
  - POST /<key>/like/ — toggle like on public drops
"""

import json
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from core.models import Drop, DropLike

pytestmark = pytest.mark.django_db


class TestPublicDropCreation:
    """POST /save/ with is_public=1."""

    def test_authenticated_can_create_public(self, client, fake_b2, starter_user):
        client.force_login(starter_user)
        resp = client.post("/save/", {
            "content": "public note",
            "key": "pub-c1",
            "is_public": "1",
        })
        assert resp.status_code == 200
        drop = Drop.objects.get(key="pub-c1")
        assert drop.is_public is True

    def test_anon_cannot_create_public(self, client, fake_b2):
        resp = client.post("/save/", {
            "content": "anon public",
            "key": "pub-c2",
            "is_public": "1",
        })
        assert resp.status_code == 200
        drop = Drop.objects.get(key="pub-c2")
        assert drop.is_public is False  # anon drops can't be public

    def test_tags_saved(self, client, fake_b2, starter_user):
        client.force_login(starter_user)
        resp = client.post("/save/", {
            "content": "tagged",
            "key": "pub-c3",
            "is_public": "1",
            "tags": "python,snippet",
        })
        assert resp.status_code == 200
        drop = Drop.objects.get(key="pub-c3")
        assert "python" in drop.tags


class TestPublicFeed:
    """GET /explore/ — the public feed."""

    def test_explore_returns_public_drops(self, client, fake_b2, starter_user):
        client.force_login(starter_user)
        client.post("/save/", {"content": "visible", "key": "exp-1", "is_public": "1"})
        client.post("/save/", {"content": "private", "key": "exp-2"})

        resp = client.get("/explore/", HTTP_ACCEPT="application/json")
        assert resp.status_code == 200
        data = resp.json()
        keys = [d["key"] for d in data["drops"]]
        assert "exp-1" in keys
        assert "exp-2" not in keys

    def test_explore_search_by_content(self, client, fake_b2, starter_user):
        client.force_login(starter_user)
        client.post("/save/", {"content": "fibonacci sequence", "key": "exp-s1", "is_public": "1"})
        client.post("/save/", {"content": "unrelated note", "key": "exp-s2", "is_public": "1"})

        resp = client.get("/explore/?q=fibonacci", HTTP_ACCEPT="application/json")
        data = resp.json()
        keys = [d["key"] for d in data["drops"]]
        assert "exp-s1" in keys
        assert "exp-s2" not in keys

    def test_explore_filter_by_tag(self, client, fake_b2, starter_user):
        client.force_login(starter_user)
        client.post("/save/", {"content": "py code", "key": "exp-t1", "is_public": "1", "tags": "python"})
        client.post("/save/", {"content": "js code", "key": "exp-t2", "is_public": "1", "tags": "javascript"})

        resp = client.get("/explore/?tag=python", HTTP_ACCEPT="application/json")
        data = resp.json()
        keys = [d["key"] for d in data["drops"]]
        assert "exp-t1" in keys
        assert "exp-t2" not in keys

    def test_explore_excludes_password_protected(self, client, fake_b2, starter_user):
        client.force_login(starter_user)
        client.post("/save/", {
            "content": "secret public", "key": "exp-pw",
            "is_public": "1", "password": "shhh",
        })

        resp = client.get("/explore/", HTTP_ACCEPT="application/json")
        data = resp.json()
        keys = [d["key"] for d in data["drops"]]
        assert "exp-pw" not in keys

    def test_explore_excludes_burn(self, client, fake_b2, starter_user):
        client.force_login(starter_user)
        client.post("/save/", {
            "content": "burn public", "key": "exp-burn",
            "is_public": "1", "burn": "1",
        })

        resp = client.get("/explore/", HTTP_ACCEPT="application/json")
        data = resp.json()
        keys = [d["key"] for d in data["drops"]]
        assert "exp-burn" not in keys

    def test_explore_empty_returns_200(self, client, fake_b2):
        resp = client.get("/explore/", HTTP_ACCEPT="application/json")
        assert resp.status_code == 200
        assert resp.json()["drops"] == []


class TestLikes:
    """POST /<key>/like/ — toggle like on public drops."""

    def test_like_toggle_on(self, client, fake_b2, starter_user, free_user):
        client.force_login(starter_user)
        client.post("/save/", {"content": "likeable", "key": "like-1", "is_public": "1"})

        client.force_login(free_user)
        resp = client.post("/like-1/like/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["liked"] is True
        assert data["like_count"] == 1

    def test_like_toggle_off(self, client, fake_b2, starter_user, free_user):
        client.force_login(starter_user)
        client.post("/save/", {"content": "unlikeable", "key": "like-2", "is_public": "1"})

        client.force_login(free_user)
        client.post("/like-2/like/")  # like
        resp = client.post("/like-2/like/")  # unlike
        assert resp.status_code == 200
        data = resp.json()
        assert data["liked"] is False
        assert data["like_count"] == 0

    def test_like_private_drop_fails(self, client, fake_b2, starter_user, free_user):
        client.force_login(starter_user)
        client.post("/save/", {"content": "private", "key": "like-3"})

        client.force_login(free_user)
        resp = client.post("/like-3/like/")
        assert resp.status_code == 404

    def test_like_requires_login(self, client, fake_b2, starter_user):
        client.force_login(starter_user)
        client.post("/save/", {"content": "x", "key": "like-4", "is_public": "1"})
        client.logout()

        resp = client.post("/like-4/like/")
        assert resp.status_code == 302  # redirect to login

    def test_like_count_in_drop_response(self, client, fake_b2, starter_user, free_user):
        client.force_login(starter_user)
        client.post("/save/", {"content": "counted", "key": "like-5", "is_public": "1"})

        client.force_login(free_user)
        client.post("/like-5/like/")

        resp = client.get("/like-5/", HTTP_ACCEPT="application/json")
        assert resp.status_code == 200
        assert resp.json()["like_count"] == 1

    def test_multiple_users_like(self, client, fake_b2, starter_user, free_user, pro_user):
        client.force_login(starter_user)
        client.post("/save/", {"content": "popular", "key": "like-6", "is_public": "1"})

        client.force_login(free_user)
        client.post("/like-6/like/")
        client.force_login(pro_user)
        client.post("/like-6/like/")

        resp = client.post("/like-6/like/")  # toggle off for pro
        data = resp.json()
        assert data["like_count"] == 1  # only free_user's like remains
