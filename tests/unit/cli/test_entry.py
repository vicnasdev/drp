"""
Tests for Entry dataclass and _entry_from_drop helper.

Verifies that server JSON is correctly mapped to Entry objects
used for listings and display.
"""

import pytest
from cli.drppath import Entry, _entry_from_drop


# ── Entry defaults ────────────────────────────────────────────────────────────


class TestEntryDefaults:
    def test_minimal_entry(self):
        e = Entry(name="readme")
        assert e.name == "readme"
        assert e.is_dir is False
        assert e.key == ""
        assert e.kind == ""
        assert e.size == 0
        assert e.locked is False
        assert e.view_count == 0
        assert e.children == []
        assert e.extra == {}

    def test_folder_entry(self):
        e = Entry(name="docs", is_dir=True, folder_id=42)
        assert e.is_dir is True
        assert e.folder_id == 42

    def test_drop_entry(self):
        e = Entry(
            name="notes.txt",
            key="abc123",
            kind="text",
            size=0,
            created="2026-01-01T00:00:00Z",
            locked=True,
        )
        assert e.key == "abc123"
        assert e.kind == "text"
        assert e.locked is True


# ── _entry_from_drop ──────────────────────────────────────────────────────────


class TestEntryFromDrop:
    def test_text_drop(self):
        data = {
            "key": "mykey",
            "kind": "text",
            "content": "hello world",
            "created_at": "2026-01-15T10:00:00Z",
            "expires_at": "2026-02-15T10:00:00Z",
            "locked": False,
            "view_count": 5,
        }
        e = _entry_from_drop(data)
        assert e.name == "mykey"  # no filename → falls back to key
        assert e.key == "mykey"
        assert e.kind == "text"
        assert e.size == 0
        assert e.created == "2026-01-15T10:00:00Z"
        assert e.expires == "2026-02-15T10:00:00Z"
        assert e.locked is False
        assert e.view_count == 5

    def test_file_drop(self):
        data = {
            "key": "abc12",
            "kind": "file",
            "filename": "report.pdf",
            "filesize": 204800,
            "created_at": "2026-02-01T12:00:00Z",
            "locked": True,
            "view_count": 12,
        }
        e = _entry_from_drop(data)
        assert e.name == "report.pdf"  # filename takes priority
        assert e.key == "abc12"
        assert e.kind == "file"
        assert e.size == 204800
        assert e.locked is True

    def test_password_protected_flag(self):
        data = {
            "key": "secret",
            "kind": "text",
            "password_protected": True,
        }
        e = _entry_from_drop(data)
        assert e.locked is True

    def test_missing_fields_use_defaults(self):
        data = {"key": "bare"}
        e = _entry_from_drop(data)
        assert e.name == "bare"
        assert e.kind == "text"
        assert e.size == 0
        assert e.created == ""
        assert e.expires == ""
        assert e.locked is False
        assert e.view_count == 0

    def test_extra_preserves_full_dict(self):
        data = {
            "key": "x",
            "kind": "text",
            "custom_field": "surprise",
        }
        e = _entry_from_drop(data)
        assert e.extra["custom_field"] == "surprise"
        assert e.extra["key"] == "x"

    def test_filename_preferred_over_key_for_name(self):
        data = {
            "key": "abc",
            "kind": "file",
            "filename": "photo.jpg",
        }
        e = _entry_from_drop(data)
        assert e.name == "photo.jpg"

    def test_no_filename_falls_back_to_key(self):
        data = {
            "key": "abc",
            "kind": "file",
            "filename": "",
        }
        e = _entry_from_drop(data)
        assert e.name == "abc"


# ── Entry as data container ──────────────────────────────────────────────────


class TestEntryUsage:
    def test_children_are_independent(self):
        """Ensure children default list is not shared between instances."""
        e1 = Entry(name="a")
        e2 = Entry(name="b")
        e1.children.append("x")
        assert e2.children == []

    def test_extra_dict_is_independent(self):
        e1 = Entry(name="a")
        e2 = Entry(name="b")
        e1.extra["foo"] = "bar"
        assert "foo" not in e2.extra
