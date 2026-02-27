"""
Integration tests: retrieving drops (JSON API) and downloading files.

Covers:
  - JSON retrieval of text and file drops
  - Raw text view
  - Download redirect for file drops
  - Burn-on-read behaviour
  - Password-protected access
"""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from core.models import Drop, Plan, UserProfile

pytestmark = pytest.mark.django_db


class TestTextRetrieval:
    """GET /<key>/ with Accept: application/json for text drops."""

    def test_retrieve_text_json(self, client, fake_b2):
        client.post("/save/", {"content": "hello retrieval", "key": "ret-t1"})
        resp = client.get("/ret-t1/", HTTP_ACCEPT="application/json")
        assert resp.status_code == 200
        data = resp.json()
        assert data["key"] == "ret-t1"
        assert data["kind"] == "text"
        assert data["content"] == "hello retrieval"

    def test_retrieve_text_html(self, client, fake_b2):
        client.post("/save/", {"content": "browser view", "key": "ret-t2"})
        resp = client.get("/ret-t2/")
        assert resp.status_code == 200
        assert b"browser view" in resp.content

    def test_raw_text_view(self, client, fake_b2):
        client.post("/save/", {"content": "raw content", "key": "ret-raw"})
        resp = client.get("/raw/ret-raw/")
        assert resp.status_code == 200
        assert resp["Content-Type"].startswith("text/plain")
        assert resp.content == b"raw content"

    def test_view_increments_count(self, client, fake_b2):
        client.post("/save/", {"content": "views", "key": "ret-vc"})
        # First view triggers the count; subsequent within 5-min debounce
        # window don't increment, so just verify it's at least 1.
        resp = client.get("/ret-vc/", HTTP_ACCEPT="application/json")
        data = resp.json()
        assert data["view_count"] >= 1

    def test_nonexistent_key_returns_404(self, client, fake_b2):
        resp = client.get("/does-not-exist/", HTTP_ACCEPT="application/json")
        assert resp.status_code == 404


class TestFileRetrieval:
    """GET /<key>/ and /<key>/download/ for file drops."""

    def test_retrieve_file_json(self, client, fake_b2):
        f = SimpleUploadedFile("data.csv", b"a,b,c\n1,2,3", content_type="text/csv")
        client.post("/save/", {"file": f, "key": "ret-f1"})
        resp = client.get("/ret-f1/", HTTP_ACCEPT="application/json")
        assert resp.status_code == 200
        data = resp.json()
        assert data["kind"] == "file"
        assert data["filename"] == "data.csv"
        assert data["filesize"] == 11
        assert "download" in data
        assert "presigned_url" in data

    def test_download_redirects_to_presigned(self, client, fake_b2):
        f = SimpleUploadedFile("archive.zip", b"PK\x03\x04fake", content_type="application/zip")
        client.post("/save/", {"file": f, "key": "ret-dl"})
        resp = client.get("/ret-dl/download/")
        assert resp.status_code == 302
        assert "fake-b2" in resp["Location"]

    def test_download_nonexistent_returns_404(self, client, fake_b2):
        resp = client.get("/nope/download/")
        assert resp.status_code == 404


class TestBurnOnRead:
    """Burn drops should be deleted after first view."""

    def test_burn_text_deleted_after_read(self, client, fake_b2):
        client.post("/save/", {"content": "secret", "key": "ret-burn", "burn": "1"})
        assert Drop.objects.filter(key="ret-burn").exists()

        resp = client.get("/ret-burn/", HTTP_ACCEPT="application/json")
        assert resp.status_code == 200
        assert resp.json()["content"] == "secret"

        # Drop should be gone now
        assert not Drop.objects.filter(key="ret-burn").exists()

    def test_burn_file_deleted_after_json_read(self, client, fake_b2, free_user):
        client.force_login(free_user)
        f = SimpleUploadedFile("burn.txt", b"classified", content_type="text/plain")
        client.post("/save/", {"file": f, "key": "ret-burnf"})
        drop = Drop.objects.get(key="ret-burnf")
        drop.burn = True
        drop.save(update_fields=["burn"])

        resp = client.get("/ret-burnf/", HTTP_ACCEPT="application/json")
        assert resp.status_code == 200

        assert not Drop.objects.filter(key="ret-burnf").exists()


class TestPasswordProtectedAccess:
    """Accessing password-protected drops."""

    def test_password_blocks_anonymous(self, client, fake_b2, starter_user):
        client.force_login(starter_user)
        client.post("/save/", {
            "content": "secret data", "key": "ret-pw1", "password": "mypass",
        })
        client.logout()

        # Anon JSON request should get 401
        resp = client.get("/ret-pw1/", HTTP_ACCEPT="application/json")
        assert resp.status_code == 401

    def test_password_header_unlocks(self, client, fake_b2, starter_user):
        client.force_login(starter_user)
        client.post("/save/", {
            "content": "unlockable", "key": "ret-pw2", "password": "pass123",
        })
        client.logout()

        resp = client.get(
            "/ret-pw2/",
            HTTP_ACCEPT="application/json",
            HTTP_X_DROP_PASSWORD="pass123",
        )
        assert resp.status_code == 200
        assert resp.json()["content"] == "unlockable"

    def test_wrong_password_stays_blocked(self, client, fake_b2, starter_user):
        client.force_login(starter_user)
        client.post("/save/", {
            "content": "nope", "key": "ret-pw3", "password": "correct",
        })
        client.logout()

        resp = client.get(
            "/ret-pw3/",
            HTTP_ACCEPT="application/json",
            HTTP_X_DROP_PASSWORD="wrong",
        )
        assert resp.status_code == 401

    def test_owner_bypasses_password(self, client, fake_b2, starter_user):
        client.force_login(starter_user)
        client.post("/save/", {
            "content": "owner access", "key": "ret-pw4", "password": "ownerpass",
        })

        # Owner should be able to read without providing password
        resp = client.get("/ret-pw4/", HTTP_ACCEPT="application/json")
        assert resp.status_code == 200
        assert resp.json()["content"] == "owner access"

    def test_password_on_raw_text(self, client, fake_b2, starter_user):
        client.force_login(starter_user)
        client.post("/save/", {
            "content": "raw secret", "key": "ret-pwraw", "password": "rawpass",
        })
        client.logout()

        # Without password
        resp = client.get("/raw/ret-pwraw/")
        assert resp.status_code == 401

        # With password header
        resp = client.get("/raw/ret-pwraw/", HTTP_X_DROP_PASSWORD="rawpass")
        assert resp.status_code == 200
        assert resp.content == b"raw secret"
