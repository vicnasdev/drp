"""
Integration tests: bookmarks (save/unsave drops to user's root folder).

POST /<key>/save/     — bookmark a drop
POST /<key>/unsave/   — unbookmark a drop
"""

import pytest

from core.models import Drop, Folder, FolderItem

pytestmark = pytest.mark.django_db


class TestSaveBookmark:
    """POST /<key>/save/ — adds drop to user's root folder."""

    def test_save_bookmark(self, client, fake_b2, starter_user):
        client.force_login(starter_user)
        client.post("/save/", {"content": "bookmarkable", "key": "bm-s1"})

        resp = client.post("/bm-s1/save/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["saved"] is True
        assert data["created"] is True

        # Drop should be in the root folder
        root = Folder.objects.get(owner=starter_user, parent=None, slug="drops")
        assert FolderItem.objects.filter(folder=root, key="bm-s1").exists()

    def test_save_idempotent(self, client, fake_b2, starter_user):
        client.force_login(starter_user)
        client.post("/save/", {"content": "twice", "key": "bm-s2"})

        client.post("/bm-s2/save/")
        resp = client.post("/bm-s2/save/")
        assert resp.status_code == 200
        assert resp.json()["created"] is False  # already saved

    def test_save_nonexistent_drop(self, client, fake_b2, starter_user):
        client.force_login(starter_user)
        resp = client.post("/ghost-key/save/")
        assert resp.status_code == 404

    def test_save_requires_login(self, client, fake_b2):
        client.post("/save/", {"content": "anon", "key": "bm-s3"})
        resp = client.post("/bm-s3/save/")
        assert resp.status_code == 302  # redirect to login

    def test_save_other_users_drop(self, client, fake_b2, starter_user, free_user):
        """You can bookmark any drop, not just your own."""
        client.force_login(starter_user)
        client.post("/save/", {"content": "shared", "key": "bm-s4"})

        client.force_login(free_user)
        resp = client.post("/bm-s4/save/")
        assert resp.status_code == 200
        assert resp.json()["saved"] is True


class TestUnsaveBookmark:
    """POST /<key>/unsave/ — removes drop from user's root folder."""

    def test_unsave_bookmark(self, client, fake_b2, starter_user):
        client.force_login(starter_user)
        client.post("/save/", {"content": "removable", "key": "bm-u1"})
        client.post("/bm-u1/save/")

        resp = client.post("/bm-u1/unsave/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["saved"] is False
        assert data["deleted"] is True

        root = Folder.objects.get(owner=starter_user, parent=None, slug="drops")
        assert not FolderItem.objects.filter(folder=root, key="bm-u1").exists()

    def test_unsave_not_saved(self, client, fake_b2, starter_user):
        client.force_login(starter_user)
        client.post("/save/", {"content": "never saved", "key": "bm-u2"})

        resp = client.post("/bm-u2/unsave/")
        assert resp.status_code == 200
        assert resp.json()["deleted"] is False

    def test_unsave_does_not_delete_drop(self, client, fake_b2, starter_user):
        client.force_login(starter_user)
        client.post("/save/", {"content": "preserve", "key": "bm-u3"})
        client.post("/bm-u3/save/")
        client.post("/bm-u3/unsave/")

        # Drop still exists
        assert Drop.objects.filter(key="bm-u3").exists()

    def test_unsave_requires_login(self, client, fake_b2):
        resp = client.post("/some-key/unsave/")
        assert resp.status_code == 302
