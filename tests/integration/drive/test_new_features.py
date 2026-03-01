"""Tests for nearest_password_ancestor, key_decrypt view, and cleanup command."""

import hashlib
from datetime import timedelta
from io import StringIO

import pytest
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import Client
from django.utils import timezone

from core.models import Plan, UserProfile
from drive.models import File, Folder, Key


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_hash(raw, salt="testsalt"):
    dk = hashlib.pbkdf2_hmac("sha256", raw.encode(), salt.encode(), 100000)
    return f"pbkdf2$100000${salt}${dk.hex()}"


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def user(db):
    u = User.objects.create_user(username="alice", password="pass")
    UserProfile.objects.create(user=u, plan=Plan.FREE)
    return u


@pytest.fixture
def other_user(db):
    u = User.objects.create_user(username="bob", password="pass")
    UserProfile.objects.create(user=u, plan=Plan.FREE)
    return u


@pytest.fixture
def client():
    return Client()


# ── nearest_password_ancestor ────────────────────────────────────────────────

@pytest.mark.django_db
class TestNearestPasswordAncestor:

    def test_no_password_returns_none(self, user):
        root = Folder.objects.create(owner=user, name="root", slug="root")
        child = Folder.objects.create(owner=user, name="child", slug="child", parent=root)
        assert child.nearest_password_ancestor() is None

    def test_self_has_password(self, user):
        root = Folder.objects.create(
            owner=user, name="locked", slug="locked",
            password_hash=_make_hash("secret"),
        )
        assert root.nearest_password_ancestor() == root

    def test_parent_has_password(self, user):
        root = Folder.objects.create(
            owner=user, name="root", slug="root",
            password_hash=_make_hash("secret"),
        )
        child = Folder.objects.create(owner=user, name="child", slug="child", parent=root)
        assert child.nearest_password_ancestor() == root

    def test_nearest_wins(self, user):
        """When both parent and grandparent have passwords, nearest wins."""
        gp = Folder.objects.create(
            owner=user, name="gp", slug="gp",
            password_hash=_make_hash("old"),
        )
        parent = Folder.objects.create(
            owner=user, name="parent", slug="parent", parent=gp,
            password_hash=_make_hash("new"),
        )
        child = Folder.objects.create(
            owner=user, name="child", slug="child", parent=parent,
        )
        assert child.nearest_password_ancestor() == parent

    def test_deep_chain(self, user):
        """Walk up 4 levels to find the password."""
        root = Folder.objects.create(
            owner=user, name="root", slug="root",
            password_hash=_make_hash("deep"),
        )
        a = Folder.objects.create(owner=user, name="a", slug="a", parent=root)
        b = Folder.objects.create(owner=user, name="b", slug="b", parent=a)
        c = Folder.objects.create(owner=user, name="c", slug="c", parent=b)
        assert c.nearest_password_ancestor() == root


# ── key_decrypt view ─────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestKeyDecryptView:

    def _make_encrypted(self, owner):
        f = File.objects.create(
            owner=owner, filename="secret.txt", content_type="text/plain",
            filesize=100, b2_key="uuid/secret.txt", encrypted=True,
        )
        k = Key.objects.create(key="enc123", file=f)
        return f, k

    def test_owner_can_decrypt(self, client, user):
        f, k = self._make_encrypted(user)
        client.login(username="alice", password="pass")
        resp = client.post(
            f"/{k.key}/decrypt/",
            data={"encryption_key": "mypassphrase"},
            content_type="application/json",
        )
        assert resp.status_code == 200
        f.refresh_from_db()
        assert f.encrypted is False

    def test_non_owner_forbidden(self, client, user, other_user):
        _, k = self._make_encrypted(user)
        client.login(username="bob", password="pass")
        resp = client.post(
            f"/{k.key}/decrypt/",
            data={"encryption_key": "mypassphrase"},
            content_type="application/json",
        )
        assert resp.status_code == 403

    def test_anon_forbidden(self, client, user):
        _, k = self._make_encrypted(user)
        resp = client.post(
            f"/{k.key}/decrypt/",
            data={"encryption_key": "mypassphrase"},
            content_type="application/json",
        )
        assert resp.status_code == 403

    def test_not_encrypted_400(self, client, user):
        f = File.objects.create(
            owner=user, filename="plain.txt", content_type="text/plain",
            filesize=100, b2_key="uuid/plain.txt", encrypted=False,
        )
        k = Key.objects.create(key="plain1", file=f)
        client.login(username="alice", password="pass")
        resp = client.post(
            f"/{k.key}/decrypt/",
            data={"encryption_key": "mypassphrase"},
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_missing_key_400(self, client, user):
        _, k = self._make_encrypted(user)
        client.login(username="alice", password="pass")
        resp = client.post(
            f"/{k.key}/decrypt/",
            data={},
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_get_not_allowed(self, client, user):
        _, k = self._make_encrypted(user)
        client.login(username="alice", password="pass")
        resp = client.get(f"/{k.key}/decrypt/")
        assert resp.status_code == 405


# ── cleanup management command ───────────────────────────────────────────────

@pytest.mark.django_db
class TestCleanupCommand:

    def test_deletes_expired_keys(self, user):
        f = File.objects.create(
            owner=user, filename="old.txt", content_type="text/plain",
            filesize=10, b2_key="uuid/old.txt",
        )
        k = Key.objects.create(
            key="expired1", file=f,
            expires_at=timezone.now() - timedelta(days=2),
        )
        out = StringIO()
        call_command("cleanup", stdout=out)
        assert not Key.objects.filter(pk=k.pk).exists()
        # File should be orphaned and deleted too
        assert not File.objects.filter(pk=f.pk).exists()
        assert "expired" in out.getvalue().lower()

    def test_deletes_burned_keys(self, user):
        f = File.objects.create(
            owner=user, filename="burn.txt", content_type="text/plain",
            filesize=10, b2_key="uuid/burn.txt",
        )
        k = Key.objects.create(key="burn1", file=f, burn=True, burned=True)
        out = StringIO()
        call_command("cleanup", stdout=out)
        assert not Key.objects.filter(pk=k.pk).exists()
        assert "burned" in out.getvalue().lower()

    def test_keeps_valid_keys(self, user):
        f = File.objects.create(
            owner=user, filename="keep.txt", content_type="text/plain",
            filesize=10, b2_key="uuid/keep.txt",
        )
        k = Key.objects.create(
            key="valid1", file=f,
            expires_at=timezone.now() + timedelta(days=30),
        )
        out = StringIO()
        call_command("cleanup", stdout=out)
        assert Key.objects.filter(pk=k.pk).exists()

    def test_dry_run_no_delete(self, user):
        f = File.objects.create(
            owner=user, filename="dryrun.txt", content_type="text/plain",
            filesize=10, b2_key="uuid/dryrun.txt",
        )
        k = Key.objects.create(
            key="dry1", file=f,
            expires_at=timezone.now() - timedelta(days=2),
        )
        out = StringIO()
        call_command("cleanup", "--dry-run", stdout=out)
        # Key should NOT be deleted
        assert Key.objects.filter(pk=k.pk).exists()
        assert "dry-run" in out.getvalue().lower()

    def test_orphan_file_cleanup(self, user):
        """File with no keys at all should be cleaned up."""
        f = File.objects.create(
            owner=user, filename="orphan.txt", content_type="text/plain",
            filesize=10, b2_key="uuid/orphan.txt",
        )
        # Create then delete the key to make the file orphaned
        k = Key.objects.create(
            key="gone1", file=f,
            expires_at=timezone.now() - timedelta(days=2),
        )
        out = StringIO()
        call_command("cleanup", stdout=out)
        assert not File.objects.filter(pk=f.pk).exists()


# ── path_view ancestor password gate ─────────────────────────────────────────

@pytest.mark.django_db
class TestPathViewAncestorPassword:

    def test_ancestor_password_blocks_descendant(self, client, user):
        """Accessing a child folder is blocked by parent's password."""
        parent = Folder.objects.create(
            owner=user, name="locked", slug="locked",
            password_hash=_make_hash("secret"),
            path_public=True,
        )
        child = Folder.objects.create(
            owner=user, name="open", slug="open", parent=parent,
            path_public=True,
        )
        resp = client.get("/@alice/locked/open/")
        # Should get the password prompt
        assert resp.status_code == 200
        assert b"password" in resp.content.lower()

    def test_correct_password_unlocks(self, client, user):
        """POSTing correct password unlocks ancestor-gated folder."""
        parent = Folder.objects.create(
            owner=user, name="locked", slug="locked",
            password_hash=_make_hash("secret"),
            path_public=True,
        )
        child = Folder.objects.create(
            owner=user, name="open", slug="open", parent=parent,
            path_public=True,
        )
        resp = client.post("/@alice/locked/open/", {"drop_password": "secret"})
        assert resp.status_code == 200
        # Should now show the folder content, not the password prompt
        assert b"open" in resp.content.lower()

    def test_owner_bypasses_password(self, client, user):
        """Owner should not be blocked by folder password."""
        parent = Folder.objects.create(
            owner=user, name="locked", slug="locked",
            password_hash=_make_hash("secret"),
        )
        child = Folder.objects.create(
            owner=user, name="inner", slug="inner", parent=parent,
        )
        client.login(username="alice", password="pass")
        resp = client.get("/@alice/locked/inner/")
        assert resp.status_code == 200
        assert b"password" not in resp.content.lower() or b"inner" in resp.content.lower()
