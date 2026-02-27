"""
Tests for pure helper functions across CLI commands.

Covers _parse_expires, _fmt_size from upload.py,
_headers, _is_binary_content, _filename_from_url from get.py,
_filename_from_response from upload.py,
_activation_line from setup.py.
"""

import pytest
from unittest.mock import MagicMock


# ── _parse_expires ────────────────────────────────────────────────────────────

from cli.commands.upload import _parse_expires


class TestParseExpires:
    def test_none_returns_none(self):      assert _parse_expires(None) is None
    def test_empty_returns_none(self):     assert _parse_expires('') is None
    def test_days(self):                   assert _parse_expires('7d') == 7
    def test_year(self):                   assert _parse_expires('1y') == 365
    def test_two_years(self):              assert _parse_expires('2y') == 730
    def test_plain_integer(self):          assert _parse_expires('30') == 30
    def test_invalid_returns_none(self):   assert _parse_expires('forever') is None
    def test_whitespace_stripped(self):     assert _parse_expires('  7d  ') == 7
    def test_case_insensitive(self):       assert _parse_expires('7D') == 7
    def test_zero_days(self):              assert _parse_expires('0d') == 0
    def test_large_year(self):             assert _parse_expires('10y') == 3650


# ── _fmt_size ─────────────────────────────────────────────────────────────────

from cli.commands.upload import _fmt_size


class TestFmtSize:
    def test_bytes(self):
        assert 'B' in _fmt_size(100)

    def test_kilobytes(self):
        assert 'KB' in _fmt_size(2048)

    def test_megabytes(self):
        assert 'MB' in _fmt_size(5 * 1024 * 1024)

    def test_gigabytes(self):
        assert 'GB' in _fmt_size(3 * 1024 ** 3)

    def test_terabytes(self):
        assert 'TB' in _fmt_size(2 * 1024 ** 4)

    def test_zero_bytes(self):
        assert _fmt_size(0) == '0 B'


# ── _headers ──────────────────────────────────────────────────────────────────

from cli.commands.get import _headers


class TestHeaders:
    def test_default_has_json_accept(self):
        h = _headers()
        assert h['Accept'] == 'application/json'
        assert 'X-Drop-Password' not in h

    def test_password_included(self):
        h = _headers('secret')
        assert h['X-Drop-Password'] == 'secret'

    def test_empty_password_excluded(self):
        h = _headers('')
        assert 'X-Drop-Password' not in h


# ── _is_binary_content ───────────────────────────────────────────────────────

from cli.commands.get import _is_binary_content


class TestIsBinaryContent:
    def test_text_html_is_not_binary(self):
        assert _is_binary_content('text/html') is False

    def test_text_plain_is_not_binary(self):
        assert _is_binary_content('text/plain') is False

    def test_application_json_is_not_binary(self):
        assert _is_binary_content('application/json') is False

    def test_application_xml_is_not_binary(self):
        assert _is_binary_content('application/xml') is False

    def test_json_with_charset_is_not_binary(self):
        assert _is_binary_content('application/json; charset=utf-8') is False

    def test_ld_json_is_not_binary(self):
        assert _is_binary_content('application/ld+json') is False

    def test_plus_xml_is_not_binary(self):
        assert _is_binary_content('application/atom+xml') is False

    def test_image_png_is_binary(self):
        assert _is_binary_content('image/png') is True

    def test_application_pdf_is_binary(self):
        assert _is_binary_content('application/pdf') is True

    def test_application_octet_stream_is_binary(self):
        assert _is_binary_content('application/octet-stream') is True

    def test_video_mp4_is_binary(self):
        assert _is_binary_content('video/mp4') is True


# ── _filename_from_url / _filename_from_response ─────────────────────────────

from cli.commands.get import _filename_from_url
from cli.commands.upload import _filename_from_response


class TestFilenameFromUrl:
    def _mock_resp(self, cd=''):
        r = MagicMock()
        r.headers = {'Content-Disposition': cd} if cd else {}
        return r

    def test_from_content_disposition_double_quotes(self):
        r = self._mock_resp('attachment; filename="report.pdf"')
        assert _filename_from_url(r, 'https://x.com/') == 'report.pdf'

    def test_from_content_disposition_single_quotes(self):
        r = self._mock_resp("attachment; filename='report.pdf'")
        assert _filename_from_url(r, 'https://x.com/') == 'report.pdf'

    def test_from_url_path(self):
        r = self._mock_resp()
        assert _filename_from_url(r, 'https://x.com/files/data.csv') == 'data.csv'

    def test_trailing_slash_uses_last_segment(self):
        r = self._mock_resp()
        assert _filename_from_url(r, 'https://x.com/api/') == 'api'

    def test_no_path_returns_download(self):
        r = self._mock_resp()
        assert _filename_from_url(r, 'https://x.com') == 'download'


class TestFilenameFromResponse:
    def _mock_resp(self, cd=''):
        r = MagicMock()
        r.headers = {'Content-Disposition': cd} if cd else {}
        return r

    def test_from_content_disposition(self):
        r = self._mock_resp('attachment; filename="file.zip"')
        assert _filename_from_response(r, 'https://x.com/') == 'file.zip'

    def test_from_url_fallback(self):
        r = self._mock_resp()
        assert _filename_from_response(r, 'https://x.com/path/doc.pdf') == 'doc.pdf'

    def test_root_url_returns_download(self):
        r = self._mock_resp()
        assert _filename_from_response(r, 'https://x.com/') == 'download'


# ── _activation_line ──────────────────────────────────────────────────────────

from cli.commands.setup import _activation_line


class TestActivationLine:
    def test_bash(self):
        line = _activation_line('bash')
        assert 'register-python-argcomplete' in line
        assert 'eval' in line

    def test_zsh_has_bashcompinit(self):
        line = _activation_line('zsh')
        assert 'bashcompinit' in line

    def test_fish_uses_source(self):
        line = _activation_line('fish')
        assert 'source' in line
        assert '--shell fish' in line

    def test_unknown_shell_returns_none(self):
        assert _activation_line('csh') is None

    def test_powershell_returns_none(self):
        assert _activation_line('powershell') is None
