"""
Integration tests: drop lifecycle — rename, copy, delete, expiry.

Exercises the action endpoints end-to-end with both text and file drops.
"""

import json
import pytest
from datetime import timedelta
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from core.models import Drop, UserProfile, Plan

pytestmark = pytest.mark.django_db


class TestDeleteDrop:
    """DELETE /<key>/delete/"""

    def test_owner_delete_own_text_drop(self, client, fake_b2, free_user):
        client.force_login(free_user)
        client.post("/save/", {"content": "goodbye", "key": "lc-del1"})
        resp = client.delete("/lc-del1/delete/")
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True
        assert not Drop.objects.filter(key="lc-del1").exists()

    def test_delete_file_removes_from_b2(self, client, fake_b2, free_user):
        client.force_login(free_user)
        f = SimpleUploadedFile("rm.txt", b"remove me", content_type="text/plain")
        client.post("/save/", {"file": f, "key": "lc-del2"})
        drop = Drop.objects.get(key="lc-del2")
        b2_key = drop.file_public_id
        assert b2_key in fake_b2.store

        resp = client.delete("/lc-del2/delete/")
        assert resp.status_code == 200
        assert b2_key not in fake_b2.store
        assert not Drop.objects.filter(key="lc-del2").exists()

    def test_other_user_cannot_delete_locked(self, client, fake_b2, starter_user, free_user):
        client.force_login(starter_user)
        client.post("/save/", {"content": "locked", "key": "lc-del3"})

        client.force_login(free_user)
        resp = client.delete("/lc-del3/delete/")
        assert resp.status_code == 403
        assert Drop.objects.filter(key="lc-del3").exists()


class TestRenameDrop:
    """POST /<key>/rename/"""

    def test_rename_text_drop(self, client, fake_b2, free_user):
        client.force_login(free_user)
        client.post("/save/", {"content": "renamable", "key": "lc-rn1"})
        resp = client.post("/lc-rn1/rename/", {"new_key": "lc-rn1-new"})
        assert resp.status_code == 200
        assert resp.json()["key"] == "lc-rn1-new"
        assert not Drop.objects.filter(key="lc-rn1").exists()
        assert Drop.objects.filter(key="lc-rn1-new").exists()

    def test_rename_file_preserves_b2_key(self, client, fake_b2, free_user):
        client.force_login(free_user)
        f = SimpleUploadedFile("doc.pdf", b"pdf-data", content_type="application/pdf")
        client.post("/save/", {"file": f, "key": "lc-rn2"})
        drop = Drop.objects.get(key="lc-rn2")
        original_b2 = drop.file_public_id

        resp = client.post("/lc-rn2/rename/", {"new_key": "lc-rn2-new"})
        assert resp.status_code == 200

        drop.refresh_from_db()
        # B2 object key should be preserved (no re-upload needed)
        assert drop.key == "lc-rn2-new"
        assert drop.file_public_id == original_b2
        assert original_b2 in fake_b2.store

    def test_rename_to_taken_key_fails(self, client, fake_b2, free_user):
        client.force_login(free_user)
        client.post("/save/", {"content": "first", "key": "lc-rn3a"})
        client.post("/save/", {"content": "second", "key": "lc-rn3b"})
        resp = client.post("/lc-rn3a/rename/", {"new_key": "lc-rn3b"})
        assert resp.status_code == 409


class TestCopyDrop:
    """POST /<key>/copy/"""

    def test_copy_text_drop(self, client, fake_b2, free_user):
        client.force_login(free_user)
        client.post("/save/", {"content": "copy me", "key": "lc-cp1"})
        resp = client.post(
            "/lc-cp1/copy/",
            data=json.dumps({"new_key": "lc-cp1-copy"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        original = Drop.objects.get(key="lc-cp1")
        copy = Drop.objects.get(key="lc-cp1-copy")
        assert copy.content == original.content
        assert copy.kind == original.kind

    def test_copy_file_drop_copies_b2(self, client, fake_b2, free_user):
        client.force_login(free_user)
        f = SimpleUploadedFile("cp.bin", b"binary data", content_type="application/octet-stream")
        client.post("/save/", {"file": f, "key": "lc-cp2"})

        resp = client.post(
            "/lc-cp2/copy/",
            data=json.dumps({"new_key": "lc-cp2-copy"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        copy = Drop.objects.get(key="lc-cp2-copy")
        assert copy.kind == Drop.FILE
        # B2 should have a copy of the object
        assert fake_b2.object_key("lc-cp2-copy") in fake_b2.store or copy.file_public_id in fake_b2.store


class TestDropExpiry:
    """Expired drops should be cleaned up on access."""

    def test_expired_text_returns_410(self, client, fake_b2):
        client.post("/save/", {"content": "ephemeral", "key": "lc-exp1"})
        drop = Drop.objects.get(key="lc-exp1")
        drop.expires_at = timezone.now() - timedelta(hours=1)
        drop.save(update_fields=["expires_at"])

        resp = client.get("/lc-exp1/", HTTP_ACCEPT="application/json")
        assert resp.status_code == 410
        assert not Drop.objects.filter(key="lc-exp1").exists()

    def test_expired_file_deleted_from_b2(self, client, fake_b2):
        f = SimpleUploadedFile("exp.txt", b"going away", content_type="text/plain")
        client.post("/save/", {"file": f, "key": "lc-exp2"})
        drop = Drop.objects.get(key="lc-exp2")
        b2_key = drop.file_public_id
        drop.expires_at = timezone.now() - timedelta(hours=1)
        drop.save(update_fields=["expires_at"])

        resp = client.get("/lc-exp2/", HTTP_ACCEPT="application/json")
        assert resp.status_code == 410
        assert b2_key not in fake_b2.store

    def test_non_expired_still_accessible(self, client, fake_b2):
        client.post("/save/", {"content": "still here", "key": "lc-exp3"})
        drop = Drop.objects.get(key="lc-exp3")
        drop.expires_at = timezone.now() + timedelta(days=30)
        drop.save(update_fields=["expires_at"])

        resp = client.get("/lc-exp3/", HTTP_ACCEPT="application/json")
        assert resp.status_code == 200
        assert resp.json()["content"] == "still here"


class TestSetPassword:
    """POST /<key>/set-password/ — paid owners only."""

    def test_set_password_on_existing_drop(self, client, fake_b2, starter_user):
        client.force_login(starter_user)
        client.post("/save/", {"content": "protect me", "key": "lc-sp1"})
        resp = client.post(
            "/lc-sp1/set-password/",
            data=json.dumps({"password": "newpass"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.json()["password_protected"] is True

        drop = Drop.objects.get(key="lc-sp1")
        assert drop.is_password_protected

    def test_remove_password(self, client, fake_b2, starter_user):
        client.force_login(starter_user)
        client.post("/save/", {"content": "was protected", "key": "lc-sp2", "password": "old"})
        resp = client.post(
            "/lc-sp2/set-password/",
            data=json.dumps({"password": ""}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.json()["password_protected"] is False

    def test_free_user_cannot_set_password(self, client, fake_b2, free_user):
        client.force_login(free_user)
        client.post("/save/", {"content": "free drop", "key": "lc-sp3"})
        resp = client.post(
            "/lc-sp3/set-password/",
            data=json.dumps({"password": "nope"}),
            content_type="application/json",
        )
        assert resp.status_code == 403
