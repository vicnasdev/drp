"""
test_edge_cases.py — error paths, bad input, special characters.

Runs real CLI commands against the live server.
"""

from tests.integration.test_lifecycle import drp, unique_key


class TestEdgeCases:

    def test_empty_stdin_upload(self):
        """drp up with empty stdin still uploads (empty text drop)."""
        k = unique_key("empty")
        rc, out, _ = drp("up", "-k", k, stdin="")
        assert rc == 0
        assert k in out
        drp("rm", k)

    def test_get_url_flag(self):
        """drp get <key> --url prints URL without fetching."""
        k = unique_key("url")
        drp("up", "url test", "-k", k)

        rc, out, _ = drp("get", k, "--url")
        assert rc == 0
        assert k in out
        assert "http" in out.lower()

        drp("rm", k)

    def test_duplicate_key_rejected(self):
        """Uploading to an existing key fails (409 conflict)."""
        k = unique_key("dup")
        drp("up", "version 1", "-k", k)

        rc, out, err = drp("up", "version 2", "-k", k)
        assert rc != 0 or "taken" in (out + err).lower() or "conflict" in (out + err).lower()

        drp("rm", k)

    def test_special_chars_in_content(self):
        """Content with quotes, newlines, unicode survives roundtrip."""
        k = unique_key("sp")
        content = 'line1\n"quoted"\nüñïcödé\n{json: true}'

        rc, _, _ = drp("up", content, "-k", k)
        assert rc == 0

        rc, out, _ = drp("get", k)
        assert rc == 0
        assert "quoted" in out
        assert "ñ" in out

        drp("rm", k)

    def test_smart_parse(self):
        """drp get <key> --parse detects format."""
        k = unique_key("parse")
        drp("up", '{"name": "test", "value": 42}', "-k", k)

        rc, out, _ = drp("get", k, "--parse")
        assert rc == 0
        assert "name" in out

        drp("rm", k)

    def test_field_extraction(self):
        """drp get <key> --field <path> extracts nested value."""
        k = unique_key("field")
        drp("up", '{"data": {"name": "drp"}}', "-k", k)

        rc, out, _ = drp("get", k, "--field", "data.name")
        assert rc == 0
        assert "drp" in out

        drp("rm", k)

    def test_dot_access_shorthand(self):
        """drp get <key>.field is shorthand for --field."""
        k = unique_key("dot")
        drp("up", '{"x": 99}', "-k", k)

        rc, out, _ = drp("get", f"{k}.x")
        assert rc == 0
        assert "99" in out

        drp("rm", k)

    def test_version(self):
        """drp --version prints a version string."""
        rc, out, _ = drp("--version")
        assert rc == 0
        assert "drp" in out.lower() or "." in out  # e.g. "drp 1.0.5"

    def test_help(self):
        """drp --help exits zero."""
        rc, out, _ = drp("--help")
        assert rc == 0
        assert "upload" in out.lower() or "drop" in out.lower()
