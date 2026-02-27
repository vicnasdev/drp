"""
Tests for resolve_any, is_drp_path, is_local_path — the path resolution layer.

These test the routing logic that decides whether a user-typed path
should become a DrpPath (drp mount) or a local pathlib.Path.
"""

import os
from pathlib import Path

import pytest
from cli.drppath import DrpPath, resolve_any, is_drp_path, is_local_path

HOST = "https://drp.test"
USER = "alice"


def _cwd() -> DrpPath:
    """A DrpPath cwd pointing at alice/docs."""
    return DrpPath("@alice/docs", HOST, None, USER)


# ── is_drp_path ──────────────────────────────────────────────────────────────


class TestIsDrpPath:
    def test_at_prefix(self):
        assert is_drp_path("@alice/docs") is True

    def test_at_only(self):
        assert is_drp_path("@") is True

    def test_bare_name(self):
        assert is_drp_path("readme") is False

    def test_dot_slash(self):
        assert is_drp_path("./foo") is False

    def test_absolute(self):
        assert is_drp_path("/tmp/foo") is False


# ── is_local_path ─────────────────────────────────────────────────────────────


class TestIsLocalPath:
    def test_dot_slash(self):
        assert is_local_path("./foo") is True

    def test_dotdot_slash(self):
        assert is_local_path("../bar") is True

    def test_absolute(self):
        assert is_local_path("/tmp/foo") is True

    def test_tilde(self):
        assert is_local_path("~/docs") is True

    def test_bare_name(self):
        assert is_local_path("readme") is False

    def test_at_prefix(self):
        assert is_local_path("@alice") is False


# ── resolve_any — outside shell (cwd=None) ───────────────────────────────────


class TestResolveOutside:
    """When cwd is None (outside shell), bare names → local, @ → drp."""

    def test_at_path_returns_drppath(self):
        r = resolve_any("@alice/docs", HOST, None, USER)
        assert isinstance(r, DrpPath)
        assert r.parts == ("alice", "docs")

    def test_dot_slash_returns_local(self):
        r = resolve_any("./foo.txt", HOST, None, USER)
        assert isinstance(r, Path)
        assert r.name == "foo.txt"

    def test_absolute_returns_local(self):
        r = resolve_any("/tmp/test", HOST, None, USER)
        assert isinstance(r, Path)
        assert r == Path("/tmp/test").resolve()

    def test_tilde_returns_local(self):
        r = resolve_any("~/docs", HOST, None, USER)
        assert isinstance(r, Path)
        assert str(r).startswith(os.path.expanduser("~"))

    def test_bare_name_returns_local(self):
        r = resolve_any("readme.md", HOST, None, USER)
        assert isinstance(r, Path)

    def test_strips_whitespace(self):
        r = resolve_any("  @alice/docs  ", HOST, None, USER)
        assert isinstance(r, DrpPath)
        assert r.parts == ("alice", "docs")


# ── resolve_any — inside shell (cwd set) ─────────────────────────────────────


class TestResolveInsideShell:
    """When cwd is set, bare names → drp child of cwd."""

    def test_bare_name_becomes_drp_child(self):
        cwd = _cwd()
        r = resolve_any("readme", HOST, None, USER, cwd=cwd)
        assert isinstance(r, DrpPath)
        assert r.parts == ("alice", "docs", "readme")

    def test_dot_slash_still_local(self):
        cwd = _cwd()
        r = resolve_any("./local.txt", HOST, None, USER, cwd=cwd)
        assert isinstance(r, Path)

    def test_dotdot_slash_still_local(self):
        cwd = _cwd()
        r = resolve_any("../parent.txt", HOST, None, USER, cwd=cwd)
        assert isinstance(r, Path)

    def test_absolute_still_local(self):
        cwd = _cwd()
        r = resolve_any("/etc/hosts", HOST, None, USER, cwd=cwd)
        assert isinstance(r, Path)
        assert r == Path("/etc/hosts").resolve()

    def test_at_path_still_drp(self):
        cwd = _cwd()
        r = resolve_any("@bob/stuff", HOST, None, USER, cwd=cwd)
        assert isinstance(r, DrpPath)
        assert r.parts == ("bob", "stuff")

    def test_nested_bare_path(self):
        cwd = _cwd()
        r = resolve_any("sub/readme", HOST, None, USER, cwd=cwd)
        assert isinstance(r, DrpPath)
        assert str(r) == "docs/sub/readme"


# ── Edge cases ────────────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_empty_string_outside_shell(self):
        r = resolve_any("", HOST, None, USER)
        assert isinstance(r, Path)

    def test_at_only(self):
        r = resolve_any("@", HOST, None, USER)
        assert isinstance(r, DrpPath)

    def test_tilde_only(self):
        r = resolve_any("~", HOST, None, USER)
        assert isinstance(r, Path)
        assert str(r) == os.path.expanduser("~")
