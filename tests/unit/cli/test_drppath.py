"""
Tests for DrpPath — path algebra, str/repr, api_path, resolve.

All tests use a dummy session (None) since path algebra never hits the network.
"""

import pytest
from cli.drppath import DrpPath

HOST = "https://drp.test"
USER = "alice"


def _p(path: str = "") -> DrpPath:
    """Shorthand: make a DrpPath for alice."""
    return DrpPath(path, HOST, None, USER)


# ── Construction & normalisation ──────────────────────────────────────────────


class TestConstruction:
    def test_empty_string_gives_root(self):
        p = _p("")
        assert p.parts == ()
        assert p.is_root

    def test_at_user_gives_root(self):
        p = _p("@alice")
        assert p.parts == ("alice",)
        assert p.is_root

    def test_strips_leading_trailing_slashes(self):
        p = _p("/alice/docs/")
        assert p.parts == ("alice", "docs")

    def test_collapses_empty_segments(self):
        p = _p("alice//docs///readme")
        assert p.parts == ("alice", "docs", "readme")

    def test_strips_at_prefix(self):
        p = _p("@alice/docs")
        assert p.parts == ("alice", "docs")


# ── Display (str / repr) ─────────────────────────────────────────────────────


class TestDisplay:
    def test_root_shows_slash(self):
        assert str(_p("")) == "/"
        assert str(_p("@alice")) == "/"

    def test_folder_no_at_prefix(self):
        assert str(_p("@alice/docs")) == "docs"

    def test_nested_no_at_prefix(self):
        assert str(_p("@alice/docs/sub/readme")) == "docs/sub/readme"

    def test_bare_key_no_user(self):
        p = DrpPath("mykey", HOST, None, USER)
        assert str(p) == "mykey"

    def test_repr_wraps_str(self):
        p = _p("@alice/docs")
        assert repr(p) == "DrpPath('docs')"


# ── api_path ──────────────────────────────────────────────────────────────────


class TestApiPath:
    def test_root_returns_username(self):
        assert _p("").api_path == USER

    def test_folder_includes_username(self):
        assert _p("@alice/docs").api_path == "alice/docs"

    def test_nested_includes_full_path(self):
        assert _p("@alice/docs/sub").api_path == "alice/docs/sub"


# ── Properties: name, parent, is_root ─────────────────────────────────────────


class TestProperties:
    def test_name_of_root_is_empty(self):
        assert _p("").name == ""

    def test_name_returns_last_part(self):
        assert _p("@alice/docs/readme").name == "readme"

    def test_parent_of_folder(self):
        p = _p("@alice/docs")
        assert p.parent.parts == ("alice",)
        assert p.parent.is_root

    def test_parent_of_nested(self):
        p = _p("@alice/docs/sub/readme")
        assert p.parent.parts == ("alice", "docs", "sub")

    def test_parent_of_root_is_root(self):
        p = _p("")
        assert p.parent.is_root

    def test_is_root_true_for_empty(self):
        assert _p("").is_root is True

    def test_is_root_true_for_username(self):
        assert _p("@alice").is_root is True

    def test_is_root_false_for_folder(self):
        assert _p("@alice/docs").is_root is False


# ── Path algebra: __truediv__ ─────────────────────────────────────────────────


class TestDivision:
    def test_root_div_child(self):
        p = _p("@alice") / "docs"
        assert p.parts == ("alice", "docs")
        assert str(p) == "docs"

    def test_folder_div_child(self):
        p = _p("@alice/docs") / "readme"
        assert str(p) == "docs/readme"

    def test_chained_divisions(self):
        p = _p("@alice") / "a" / "b" / "c"
        assert p.parts == ("alice", "a", "b", "c")
        assert str(p) == "a/b/c"


# ── resolve() ────────────────────────────────────────────────────────────────


class TestResolve:
    def test_absolute_at_path(self):
        base = _p("@alice/docs")
        r = base.resolve("@bob/stuff")
        assert r.parts == ("bob", "stuff")

    def test_absolute_slash_path(self):
        base = _p("@alice/docs")
        r = base.resolve("/other")
        assert r.parts == ("alice", "other")

    def test_relative_child(self):
        base = _p("@alice/docs")
        r = base.resolve("readme")
        assert r.parts == ("alice", "docs", "readme")

    def test_dotdot_goes_up(self):
        base = _p("@alice/docs/sub")
        r = base.resolve("../readme")
        assert r.parts == ("alice", "docs", "readme")

    def test_dot_stays(self):
        base = _p("@alice/docs")
        r = base.resolve("./readme")
        assert r.parts == ("alice", "docs", "readme")


# ── URL helpers ───────────────────────────────────────────────────────────────


class TestUrls:
    def test_url_root(self):
        assert _p("").url() == f"{HOST}/@{USER}/"

    def test_url_folder(self):
        assert _p("@alice/docs").url() == f"{HOST}/@alice/docs/"

    def test_download_url(self):
        p = _p("mykey")
        assert p.download_url() == f"{HOST}/mykey/download/"

    def test_raw_url(self):
        p = _p("mykey")
        assert p.raw_url() == f"{HOST}/raw/mykey/"
