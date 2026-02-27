"""
Integration tests: file upload via web form (multipart POST /save/).

Exercises the full cycle:
  upload file → B2 stores bytes → Drop model created → retrieve JSON → download redirect
"""

import io
import pytest
from unittest.mock import patch
from django.core.files.uploadedfile import SimpleUploadedFile

from core.models import Drop

pytestmark = pytest.mark.django_db


class TestFileUploadWeb:
    """POST /save/ with a file — the browser / web upload path."""

    def test_anon_file_upload(self, client, fake_b2):
        f = SimpleUploadedFile("hello.txt", b"hello world", content_type="text/plain")
        resp = client.post("/save/", {"file": f, "key": "int-f1"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["key"] == "int-f1"
        assert data["kind"] == "file"

        drop = Drop.objects.get(key="int-f1")
        assert drop.kind == Drop.FILE
        assert drop.filename == "hello.txt"
        assert drop.filesize == 11

        # B2 should have the bytes
        b2_key = drop.file_public_id or f"drops/f/int-f1"
        assert b2_key in fake_b2.store
        assert fake_b2.store[b2_key] == b"hello world"

    def test_authenticated_file_upload(self, client, fake_b2, starter_user):
        client.force_login(starter_user)
        f = SimpleUploadedFile("report.pdf", b"%PDF-1.4 fake", content_type="application/pdf")
        resp = client.post("/save/", {"file": f, "key": "int-f2"})
        assert resp.status_code == 200

        drop = Drop.objects.get(key="int-f2")
        assert drop.owner == starter_user
        assert drop.locked is True  # paid user → locked
        assert drop.content_type == "application/pdf"

    def test_file_overwrite_replaces_b2_content(self, client, fake_b2):
        f1 = SimpleUploadedFile("v1.txt", b"version one", content_type="text/plain")
        client.post("/save/", {"file": f1, "key": "int-ow"})
        f2 = SimpleUploadedFile("v2.txt", b"version two!", content_type="text/plain")
        client.post("/save/", {"file": f2, "key": "int-ow"})

        drop = Drop.objects.get(key="int-ow")
        assert drop.filename == "v2.txt"
        b2_key = drop.file_public_id
        assert fake_b2.store[b2_key] == b"version two!"

    def test_large_file_rejected_for_free(self, client, fake_b2, free_user):
        client.force_login(free_user)
        # Patch max_file_bytes to return 100 bytes so we can test the limit
        # without sending 200+ MB through the test harness.
        with patch("core.views.drops.max_file_bytes", return_value=100):
            big = b"x" * 200
            f = SimpleUploadedFile("big.bin", big, content_type="application/octet-stream")
            resp = client.post("/save/", {"file": f, "key": "int-big"})
        assert resp.status_code == 400
        assert "limit" in resp.json()["error"].lower() or "exceeds" in resp.json()["error"].lower()

    def test_file_upload_returns_url(self, client, fake_b2):
        f = SimpleUploadedFile("pic.png", b"\x89PNG\r\n", content_type="image/png")
        resp = client.post("/save/", {"file": f, "key": "int-url"})
        data = resp.json()
        assert data["url"] == "/int-url/"


class TestFileUploadCLI:
    """Two-step upload: POST /upload/prepare/ + POST /upload/confirm/."""

    def test_prepare_returns_presigned_url(self, client, fake_b2, free_user):
        client.force_login(free_user)
        resp = client.post(
            "/upload/prepare/",
            data='{"filename": "data.csv", "size": 1024, "content_type": "text/csv", "key": "int-cli1"}',
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "presigned_url" in data
        assert data["key"] == "int-cli1"

    def test_prepare_then_confirm(self, client, fake_b2, starter_user):
        client.force_login(starter_user)

        # Step 1: prepare
        resp = client.post(
            "/upload/prepare/",
            data='{"filename": "notes.md", "size": 42, "content_type": "text/markdown", "key": "int-cli2"}',
            content_type="application/json",
        )
        assert resp.status_code == 200

        # Simulate the client uploading to B2
        fake_b2.store["drops/f/int-cli2"] = b"# Notes\nSome markdown content here."

        # Step 2: confirm
        resp = client.post(
            "/upload/confirm/",
            data='{"key": "int-cli2", "filename": "notes.md", "content_type": "text/markdown"}',
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["key"] == "int-cli2"
        assert data["kind"] == "file"

        drop = Drop.objects.get(key="int-cli2")
        assert drop.filename == "notes.md"
        assert drop.filesize == len(b"# Notes\nSome markdown content here.")

    def test_confirm_without_file_in_b2_fails(self, client, fake_b2, free_user):
        client.force_login(free_user)
        resp = client.post(
            "/upload/confirm/",
            data='{"key": "ghost-key", "filename": "ghost.txt"}',
            content_type="application/json",
        )
        assert resp.status_code == 404
        assert "not found" in resp.json()["error"].lower()

    def test_key_collision_auto_resolves(self, client, fake_b2, free_user, starter_user):
        # Create a locked drop as starter
        client.force_login(starter_user)
        client.post("/save/", {"content": "mine", "key": "shared-key"})

        # Try to prepare as free user with same key
        client.force_login(free_user)
        resp = client.post(
            "/upload/prepare/",
            data='{"filename": "other.txt", "size": 5, "key": "shared-key"}',
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.json()
        # Should have been auto-resolved to a different key
        assert data["key"] != "shared-key"
        assert data["key"].startswith("shared-key-")
