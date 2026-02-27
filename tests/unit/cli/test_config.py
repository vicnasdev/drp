"""
Tests for cli.config — config CRUD and local drop list management.

Uses tmp_path so no real filesystem pollution.
"""

import json
import pytest

from cli import config


# ── load / save ───────────────────────────────────────────────────────────────

class TestLoad:
    def test_missing_file_returns_empty_dict(self, tmp_path):
        assert config.load(tmp_path / "nope.json") == {}

    def test_roundtrip(self, tmp_path):
        p = tmp_path / "cfg.json"
        config.save({"host": "https://drp.test", "ansi": True}, p)
        got = config.load(p)
        assert got["host"] == "https://drp.test"
        assert got["ansi"] is True

    def test_save_creates_parent_dirs(self, tmp_path):
        p = tmp_path / "deep" / "nested" / "cfg.json"
        config.save({"x": 1}, p)
        assert config.load(p) == {"x": 1}

    def test_save_overwrites_existing(self, tmp_path):
        p = tmp_path / "cfg.json"
        config.save({"a": 1}, p)
        config.save({"b": 2}, p)
        got = config.load(p)
        assert "a" not in got
        assert got["b"] == 2

    def test_preserves_unicode(self, tmp_path):
        p = tmp_path / "cfg.json"
        config.save({"name": "café ☕"}, p)
        assert config.load(p)["name"] == "café ☕"


# ── Local drop list ──────────────────────────────────────────────────────────

class TestLocalDrops:
    @pytest.fixture(autouse=True)
    def _patch_drops_file(self, tmp_path, monkeypatch):
        self.drops_file = tmp_path / "drops.json"
        monkeypatch.setattr(config, "DROPS_FILE", self.drops_file)

    def test_empty_when_no_file(self):
        assert config.load_local_drops() == []

    def test_save_and_load(self):
        drops = [{"key": "a", "kind": "c"}, {"key": "b", "kind": "f"}]
        config.save_local_drops(drops)
        assert config.load_local_drops() == drops

    def test_corrupt_file_returns_empty(self):
        self.drops_file.parent.mkdir(parents=True, exist_ok=True)
        self.drops_file.write_text("not json!!!")
        assert config.load_local_drops() == []


class TestRecordDrop:
    @pytest.fixture(autouse=True)
    def _patch_drops_file(self, tmp_path, monkeypatch):
        self.drops_file = tmp_path / "drops.json"
        monkeypatch.setattr(config, "DROPS_FILE", self.drops_file)

    def test_stores_key_and_kind(self):
        config.record_drop("hello", "c")
        drops = config.load_local_drops()
        assert len(drops) == 1
        assert drops[0]["key"] == "hello"
        assert drops[0]["kind"] == "c"

    def test_file_drop_stores_kind_f(self):
        config.record_drop("report", "f", filename="report.pdf")
        d = config.load_local_drops()[0]
        assert d["kind"] == "f"
        assert d["filename"] == "report.pdf"

    def test_most_recent_first(self):
        config.record_drop("first", "c")
        config.record_drop("second", "c")
        drops = config.load_local_drops()
        assert drops[0]["key"] == "second"
        assert drops[1]["key"] == "first"

    def test_duplicate_key_replaces(self):
        config.record_drop("x", "c")
        config.record_drop("x", "f")
        drops = config.load_local_drops()
        assert len(drops) == 1
        assert drops[0]["kind"] == "f"

    def test_stores_host(self):
        config.record_drop("k", "c", host="https://drp.test")
        assert config.load_local_drops()[0]["host"] == "https://drp.test"

    def test_has_created_at(self):
        config.record_drop("k", "c")
        assert "created_at" in config.load_local_drops()[0]


class TestRemoveAndRename:
    @pytest.fixture(autouse=True)
    def _patch_drops_file(self, tmp_path, monkeypatch):
        self.drops_file = tmp_path / "drops.json"
        monkeypatch.setattr(config, "DROPS_FILE", self.drops_file)

    def test_remove_only_target(self):
        config.record_drop("a", "c")
        config.record_drop("b", "c")
        config.remove_local_drop("a")
        keys = [d["key"] for d in config.load_local_drops()]
        assert keys == ["b"]

    def test_remove_nonexistent_is_noop(self):
        config.record_drop("a", "c")
        config.remove_local_drop("zzz")
        assert len(config.load_local_drops()) == 1

    def test_rename_updates_key(self):
        config.record_drop("old", "c")
        config.rename_local_drop("old", "new")
        keys = [d["key"] for d in config.load_local_drops()]
        assert keys == ["new"]

    def test_rename_preserves_other_fields(self):
        config.record_drop("old", "f", filename="doc.pdf")
        config.rename_local_drop("old", "new")
        d = config.load_local_drops()[0]
        assert d["filename"] == "doc.pdf"
        assert d["kind"] == "f"

    def test_rename_nonexistent_is_noop(self):
        config.record_drop("a", "c")
        config.rename_local_drop("zzz", "nope")
        assert config.load_local_drops()[0]["key"] == "a"
