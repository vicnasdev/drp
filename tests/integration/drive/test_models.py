"""Tests for drive models — Folder, File, Key, Like, Bookmark."""

import pytest
from datetime import timedelta

from django.contrib.auth.models import User
from django.db import IntegrityError
from django.utils import timezone

from core.models import Plan, PlanLimits, UserProfile
from drive.models import Bookmark, File, Folder, Key, Like, _generate_key


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
def folder(user):
    return Folder.objects.create(owner=user, name="docs", slug="docs")


@pytest.fixture
def nested_folder(user, folder):
    return Folder.objects.create(
        owner=user, name="reports", slug="reports", parent=folder,
    )


@pytest.fixture
def file(user, folder):
    return File.objects.create(
        owner=user, folder=folder, filename="readme.md",
        content_type="text/markdown", filesize=1024, b2_key="abc/readme.md",
    )


@pytest.fixture
def key(file):
    return Key.objects.create(key="xK9mZ2", file=file)


# ── _generate_key ────────────────────────────────────────────────────────────

def test_generate_key_length():
    k = _generate_key(8)
    assert len(k) == 8


def test_generate_key_alphanumeric():
    k = _generate_key(100)
    assert k.isalnum()


def test_generate_key_unique():
    keys = {_generate_key() for _ in range(100)}
    assert len(keys) == 100  # astronomically unlikely collision


# ── Folder ───────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestFolder:
    def test_str_root(self, folder):
        assert str(folder) == "/docs/"

    def test_str_nested(self, nested_folder):
        assert str(nested_folder) == "/docs/reports/"

    def test_full_path_root(self, folder):
        assert folder.full_path == "/docs/"

    def test_full_path_nested(self, nested_folder):
        assert nested_folder.full_path == "/docs/reports/"

    def test_is_password_protected_false(self, folder):
        assert not folder.is_password_protected

    def test_is_password_protected_true(self, folder):
        folder.password_hash = "pbkdf2$100000$salt$hash"
        assert folder.is_password_protected

    def test_path_access_default_denied(self, folder):
        assert not folder.path_access_allowed()

    def test_path_access_enabled(self, folder):
        folder.path_public = True
        folder.save()
        assert folder.path_access_allowed()

    def test_path_access_inherited(self, folder, nested_folder):
        """Child inherits path access from parent."""
        folder.path_public = True
        folder.save()
        assert nested_folder.path_access_allowed()

    def test_path_access_not_inherited_upward(self, folder, nested_folder):
        """Parent does NOT inherit from child."""
        nested_folder.path_public = True
        nested_folder.save()
        assert not folder.path_access_allowed()

    def test_unique_slug_per_parent(self, user, folder):
        """No duplicate slugs under the same parent."""
        # Create a child under folder
        Folder.objects.create(
            owner=user, name="sub", slug="sub", parent=folder,
        )
        with pytest.raises(IntegrityError):
            Folder.objects.create(
                owner=user, name="sub2", slug="sub", parent=folder,
            )

    def test_same_slug_different_parent(self, user, folder):
        """Same slug under different parents is fine."""
        Folder.objects.create(
            owner=user, name="docs", slug="docs", parent=folder,
        )
        assert Folder.objects.filter(slug="docs").count() == 2


# ── File ─────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestFile:
    def test_str(self, file):
        assert str(file) == "readme.md"

    def test_unique_filename_per_folder(self, user, folder):
        File.objects.create(
            owner=user, folder=folder, filename="a.txt",
            b2_key="x/a.txt",
        )
        with pytest.raises(IntegrityError):
            File.objects.create(
                owner=user, folder=folder, filename="a.txt",
                b2_key="y/a.txt",
            )

    def test_same_filename_no_folder(self, user):
        """Files without a folder aren't constrained on name."""
        File.objects.create(
            owner=user, folder=None, filename="loose.txt",
            b2_key="x/loose.txt",
        )
        File.objects.create(
            owner=user, folder=None, filename="loose.txt",
            b2_key="y/loose.txt",
        )
        assert File.objects.filter(filename="loose.txt").count() == 2

    def test_encrypted_default(self, file):
        assert not file.encrypted


# ── Key ──────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestKey:
    def test_str(self, key):
        assert str(key) == "xK9mZ2"

    def test_unique_key(self, file):
        Key.objects.create(key="abc123", file=file)
        with pytest.raises(IntegrityError):
            Key.objects.create(key="abc123", file=file)

    def test_is_valid_fresh(self, key):
        assert key.is_valid

    def test_is_expired_none(self, key):
        assert not key.is_expired

    def test_is_expired_future(self, key):
        key.expires_at = timezone.now() + timedelta(days=7)
        assert not key.is_expired

    def test_is_expired_past(self, key):
        key.expires_at = timezone.now() - timedelta(seconds=1)
        assert key.is_expired

    def test_is_valid_expired(self, key):
        key.expires_at = timezone.now() - timedelta(seconds=1)
        assert not key.is_valid

    def test_burn_fresh(self, key):
        key.burn = True
        assert not key.is_burned
        assert key.is_valid

    def test_burn_after_mark(self, key):
        key.burn = True
        key.save()
        key.mark_burned()
        key.refresh_from_db()
        assert key.is_burned
        assert not key.is_valid

    def test_mark_burned_no_op_when_not_burn(self, key):
        key.mark_burned()
        assert not key.burned

    def test_is_password_protected(self, key):
        assert not key.is_password_protected
        key.password_hash = "pbkdf2$100000$salt$hash"
        assert key.is_password_protected

    # ── Proxy properties ──
    def test_proxy_filename(self, key):
        assert key.filename == "readme.md"

    def test_proxy_content_type(self, key):
        assert key.content_type == "text/markdown"

    def test_proxy_filesize(self, key):
        assert key.filesize == 1024

    def test_proxy_owner(self, key, user):
        assert key.owner == user

    def test_proxy_encrypted(self, key):
        assert key.encrypted is False

    def test_publish_default(self, key):
        assert not key.publish

    def test_tags_default(self, key):
        assert key.tags == []


# ── Like ─────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestLike:
    def test_one_like_per_user(self, key, user):
        Like.objects.create(key=key, user=user)
        with pytest.raises(IntegrityError):
            Like.objects.create(key=key, user=user)

    def test_one_like_per_ip(self, key):
        Like.objects.create(key=key, ip="1.2.3.4")
        with pytest.raises(IntegrityError):
            Like.objects.create(key=key, ip="1.2.3.4")

    def test_different_users_can_like(self, key, user, pro_user):
        Like.objects.create(key=key, user=user)
        Like.objects.create(key=key, user=pro_user)
        assert Like.objects.filter(key=key).count() == 2


# ── Bookmark ─────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestBookmark:
    def test_one_bookmark_per_user_key(self, key, user):
        Bookmark.objects.create(user=user, key=key)
        with pytest.raises(IntegrityError):
            Bookmark.objects.create(user=user, key=key)

    def test_different_users_can_bookmark(self, key, user, pro_user):
        Bookmark.objects.create(user=user, key=key)
        Bookmark.objects.create(user=pro_user, key=key)
        assert Bookmark.objects.filter(key=key).count() == 2
