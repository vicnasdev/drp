"""Integration tests for drive views — key pages, profile, explore, path access."""

import pytest
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import Client
from django.utils import timezone

from core.models import Plan, UserProfile
from drive.models import File, Folder, Key


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def user(db):
    u = User.objects.create_user(username="alice", password="pass")
    UserProfile.objects.create(user=u, plan=Plan.FREE)
    return u


@pytest.fixture
def pro_user(db):
    u = User.objects.create_user(username="bob", password="pass")
    UserProfile.objects.create(user=u, plan=Plan.PRO)
    return u


@pytest.fixture
def client():
    return Client()


@pytest.fixture
def file_and_key(user):
    f = File.objects.create(
        owner=user, filename="hello.txt", content_type="text/plain",
        filesize=5, b2_key="uuid/hello.txt",
    )
    k = Key.objects.create(key="abc123", file=f)
    return f, k


# ── Key view ─────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestKeyView:
    def test_valid_key_200(self, client, file_and_key):
        _, k = file_and_key
        resp = client.get(f"/{k.key}/")
        assert resp.status_code == 200

    def test_invalid_key_404(self, client):
        resp = client.get("/nonexistent/")
        assert resp.status_code == 404

    def test_expired_key_410(self, client, file_and_key):
        _, k = file_and_key
        k.expires_at = timezone.now() - timedelta(seconds=1)
        k.save()
        resp = client.get(f"/{k.key}/")
        assert resp.status_code == 410

    def test_burned_key_410(self, client, file_and_key):
        _, k = file_and_key
        k.burn = True
        k.burned = True
        k.save()
        resp = client.get(f"/{k.key}/")
        assert resp.status_code == 410

    def test_burn_after_read(self, client, file_and_key):
        _, k = file_and_key
        k.burn = True
        k.save()
        # First view succeeds
        resp1 = client.get(f"/{k.key}/")
        assert resp1.status_code == 200
        # Second view shows expired
        resp2 = client.get(f"/{k.key}/")
        assert resp2.status_code == 410

    def test_password_prompt(self, client, file_and_key):
        _, k = file_and_key
        k.password_hash = "pbkdf2$100000$salt$fakehash"
        k.save()
        resp = client.get(f"/{k.key}/")
        assert resp.status_code == 200
        assert b"password required" in resp.content


# ── Key raw / download ───────────────────────────────────────────────────────

@pytest.mark.django_db
class TestKeyRawDownload:
    def test_raw_valid(self, client, file_and_key):
        _, k = file_and_key
        resp = client.get(f"/{k.key}/raw/")
        assert resp.status_code == 200

    def test_raw_expired_404(self, client, file_and_key):
        _, k = file_and_key
        k.expires_at = timezone.now() - timedelta(seconds=1)
        k.save()
        resp = client.get(f"/{k.key}/raw/")
        assert resp.status_code == 404

    def test_download_valid(self, client, file_and_key):
        _, k = file_and_key
        resp = client.get(f"/{k.key}/download/")
        assert resp.status_code == 200
        assert "attachment" in resp["Content-Disposition"]

    def test_download_expired_404(self, client, file_and_key):
        _, k = file_and_key
        k.expires_at = timezone.now() - timedelta(seconds=1)
        k.save()
        resp = client.get(f"/{k.key}/download/")
        assert resp.status_code == 404


# ── Embed ────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestEmbed:
    def test_embed_valid(self, client, file_and_key):
        _, k = file_and_key
        resp = client.get(f"/embed/{k.key}/")
        assert resp.status_code == 200

    def test_embed_expired_404(self, client, file_and_key):
        _, k = file_and_key
        k.expires_at = timezone.now() - timedelta(seconds=1)
        k.save()
        resp = client.get(f"/embed/{k.key}/")
        assert resp.status_code == 404


# ── Explore ──────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestExplore:
    def test_explore_empty(self, client):
        resp = client.get("/explore/")
        assert resp.status_code == 200

    def test_explore_shows_published(self, client, file_and_key):
        _, k = file_and_key
        k.publish = True
        k.save()
        resp = client.get("/explore/")
        assert resp.status_code == 200
        assert k.key.encode() in resp.content

    def test_explore_hides_unpublished(self, client, file_and_key):
        _, k = file_and_key
        resp = client.get("/explore/")
        assert k.key.encode() not in resp.content

    def test_explore_search(self, client, file_and_key):
        _, k = file_and_key
        k.publish = True
        k.save()
        resp = client.get("/explore/?q=hello")
        assert resp.status_code == 200

    def test_explore_tag_filter(self, client, file_and_key):
        _, k = file_and_key
        k.publish = True
        k.tags = ["python"]
        k.save()
        resp = client.get("/explore/?tag=python")
        assert k.key.encode() in resp.content

    def test_explore_sort_likes(self, client, file_and_key):
        _, k = file_and_key
        k.publish = True
        k.save()
        resp = client.get("/explore/?sort=likes")
        assert resp.status_code == 200


# ── Profile ──────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestProfile:
    def test_profile_exists(self, client, user):
        resp = client.get(f"/@{user.username}/")
        assert resp.status_code == 200

    def test_profile_404(self, client):
        resp = client.get("/@nobody/")
        assert resp.status_code == 404

    def test_owner_sees_all_folders(self, client, user):
        Folder.objects.create(owner=user, name="secret", slug="secret")
        client.login(username="alice", password="pass")
        resp = client.get(f"/@{user.username}/")
        assert b"secret" in resp.content

    def test_visitor_sees_only_path_public(self, client, user, pro_user):
        Folder.objects.create(owner=user, name="private", slug="private")
        Folder.objects.create(
            owner=user, name="open", slug="open", path_public=True,
        )
        # Visit as a different user
        client.login(username="bob", password="pass")
        resp = client.get(f"/@{user.username}/")
        assert b"open" in resp.content
        assert b"private" not in resp.content


# ── Path access ──────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestPathAccess:
    def test_owner_can_access_path(self, client, user):
        folder = Folder.objects.create(owner=user, name="docs", slug="docs")
        client.login(username="alice", password="pass")
        resp = client.get(f"/@{user.username}/docs/")
        assert resp.status_code == 200

    def test_non_owner_denied_by_default(self, client, user, pro_user):
        Folder.objects.create(owner=user, name="docs", slug="docs")
        client.login(username="bob", password="pass")
        resp = client.get(f"/@{user.username}/docs/")
        assert resp.status_code == 403

    def test_non_owner_allowed_when_path_public(self, client, user, pro_user):
        Folder.objects.create(
            owner=user, name="docs", slug="docs", path_public=True,
        )
        client.login(username="bob", password="pass")
        resp = client.get(f"/@{user.username}/docs/")
        assert resp.status_code == 200

    def test_nested_path_resolves(self, client, user):
        parent = Folder.objects.create(
            owner=user, name="docs", slug="docs", path_public=True,
        )
        Folder.objects.create(
            owner=user, name="reports", slug="reports", parent=parent,
        )
        client.login(username="alice", password="pass")
        resp = client.get(f"/@{user.username}/docs/reports/")
        assert resp.status_code == 200

    def test_file_by_path_redirects_to_key(self, client, user):
        folder = Folder.objects.create(
            owner=user, name="docs", slug="docs", path_public=True,
        )
        f = File.objects.create(
            owner=user, folder=folder, filename="notes.txt",
            content_type="text/plain", filesize=10, b2_key="x/notes.txt",
        )
        k = Key.objects.create(key="ntkey1", file=f)
        client.login(username="alice", password="pass")
        resp = client.get(f"/@{user.username}/docs/notes.txt/")
        assert resp.status_code == 302
        assert f"/{k.key}/" in resp["Location"]

    def test_path_404_for_missing(self, client, user):
        Folder.objects.create(
            owner=user, name="docs", slug="docs", path_public=True,
        )
        client.login(username="alice", password="pass")
        resp = client.get(f"/@{user.username}/docs/nonexistent/")
        assert resp.status_code == 404
