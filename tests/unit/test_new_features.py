"""
tests/unit/test_new_features.py

Tests for the new CLI features added in this batch:
  - ResilientSession: retry on ConnectionError, Timeout, 502/503/504
  - Spinners: verify key commands wrap server calls in Spinner context
  - Enhanced drp get <url>: binary detection, filename inference, streaming
  - Server-side URL upload: upload_from_url endpoint + CLI --remote flag
  - upload_from_url API function
"""

import io
import time
from unittest.mock import MagicMock, patch, call

import pytest
import requests


# ── ResilientSession ──────────────────────────────────────────────────────────

class TestResilientSession:
    """Transparent retry with exponential backoff."""

    def test_success_first_try(self):
        from cli.session import ResilientSession
        s = ResilientSession()
        mock_resp = MagicMock(status_code=200)
        with patch.object(requests.Session, 'request', return_value=mock_resp):
            resp = s.request('GET', 'http://example.com')
        assert resp.status_code == 200

    def test_retry_on_connection_error(self):
        from cli.session import ResilientSession
        s = ResilientSession()
        ok = MagicMock(status_code=200)
        effects = [requests.exceptions.ConnectionError('refused'), ok]
        with patch.object(requests.Session, 'request', side_effect=effects):
            with patch('time.sleep') as slp:
                resp = s.request('GET', 'http://example.com')
        assert resp.status_code == 200
        slp.assert_called_once_with(1)  # first backoff

    def test_retry_on_timeout(self):
        from cli.session import ResilientSession
        s = ResilientSession()
        ok = MagicMock(status_code=200)
        effects = [requests.exceptions.Timeout('timed out'), ok]
        with patch.object(requests.Session, 'request', side_effect=effects):
            with patch('time.sleep'):
                resp = s.request('GET', 'http://example.com')
        assert resp.status_code == 200

    def test_retry_on_502(self):
        from cli.session import ResilientSession
        s = ResilientSession()
        bad = MagicMock(status_code=502)
        ok  = MagicMock(status_code=200)
        with patch.object(requests.Session, 'request', side_effect=[bad, ok]):
            with patch('time.sleep'):
                resp = s.request('GET', 'http://example.com')
        assert resp.status_code == 200

    def test_retry_on_503(self):
        from cli.session import ResilientSession
        s = ResilientSession()
        bad = MagicMock(status_code=503)
        ok  = MagicMock(status_code=200)
        with patch.object(requests.Session, 'request', side_effect=[bad, ok]):
            with patch('time.sleep'):
                resp = s.request('GET', 'http://example.com')
        assert resp.status_code == 200

    def test_retry_on_504(self):
        from cli.session import ResilientSession
        s = ResilientSession()
        bad = MagicMock(status_code=504)
        ok  = MagicMock(status_code=200)
        with patch.object(requests.Session, 'request', side_effect=[bad, ok]):
            with patch('time.sleep'):
                resp = s.request('GET', 'http://example.com')
        assert resp.status_code == 200

    def test_no_retry_on_400(self):
        from cli.session import ResilientSession
        s = ResilientSession()
        bad = MagicMock(status_code=400)
        with patch.object(requests.Session, 'request', return_value=bad):
            with patch('time.sleep') as slp:
                resp = s.request('GET', 'http://example.com')
        assert resp.status_code == 400
        slp.assert_not_called()

    def test_no_retry_on_404(self):
        from cli.session import ResilientSession
        s = ResilientSession()
        bad = MagicMock(status_code=404)
        with patch.object(requests.Session, 'request', return_value=bad):
            with patch('time.sleep') as slp:
                resp = s.request('GET', 'http://example.com')
        assert resp.status_code == 404
        slp.assert_not_called()

    def test_exhausted_retries_raises_last_exception(self):
        from cli.session import ResilientSession
        s = ResilientSession()
        exc = requests.exceptions.ConnectionError('down')
        with patch.object(requests.Session, 'request', side_effect=exc):
            with patch('time.sleep'):
                with pytest.raises(requests.exceptions.ConnectionError):
                    s.request('GET', 'http://example.com')

    def test_exhausted_retries_returns_last_502(self):
        from cli.session import ResilientSession
        s = ResilientSession()
        bad = MagicMock(status_code=502)
        with patch.object(requests.Session, 'request', return_value=bad):
            with patch('time.sleep'):
                resp = s.request('GET', 'http://example.com')
        assert resp.status_code == 502

    def test_backoff_timing(self):
        from cli.session import ResilientSession, RETRY_BACKOFF
        s = ResilientSession()
        ok = MagicMock(status_code=200)
        # Fail 3 times then succeed
        effects = [
            requests.exceptions.ConnectionError(),
            requests.exceptions.ConnectionError(),
            requests.exceptions.ConnectionError(),
            ok,
        ]
        with patch.object(requests.Session, 'request', side_effect=effects):
            with patch('time.sleep') as slp:
                s.request('GET', 'http://example.com')
        expected = [call(RETRY_BACKOFF[0]), call(RETRY_BACKOFF[1]), call(RETRY_BACKOFF[2])]
        assert slp.call_args_list == expected


# ── Binary content detection ──────────────────────────────────────────────────

class TestIsBinaryContent:
    def _f(self, ct):
        from cli.commands.get import _is_binary_content
        return _is_binary_content(ct)

    def test_text_html(self):
        assert not self._f('text/html')

    def test_text_plain(self):
        assert not self._f('text/plain')

    def test_application_json(self):
        assert not self._f('application/json')

    def test_application_xml(self):
        assert not self._f('application/xml')

    def test_application_yaml(self):
        assert not self._f('application/yaml')

    def test_json_ld(self):
        assert not self._f('application/ld+json')

    def test_plus_json_suffix(self):
        assert not self._f('application/vnd.api+json')

    def test_plus_xml_suffix(self):
        assert not self._f('application/atom+xml')

    def test_octet_stream(self):
        assert self._f('application/octet-stream')

    def test_pdf(self):
        assert self._f('application/pdf')

    def test_image_png(self):
        assert self._f('image/png')

    def test_video_mp4(self):
        assert self._f('video/mp4')

    def test_audio_mpeg(self):
        assert self._f('audio/mpeg')

    def test_zip(self):
        assert self._f('application/zip')

    def test_content_type_with_charset(self):
        assert not self._f('text/html; charset=utf-8')

    def test_application_javascript(self):
        assert not self._f('application/javascript')


# ── Filename inference from URL ───────────────────────────────────────────────

class TestFilenameFromUrl:
    def _f(self, headers, url):
        from cli.commands.get import _filename_from_url
        mock_resp = MagicMock()
        mock_resp.headers = headers
        return _filename_from_url(mock_resp, url)

    def test_from_content_disposition(self):
        name = self._f({'Content-Disposition': 'attachment; filename="report.pdf"'},
                       'https://example.com/download/')
        assert name == 'report.pdf'

    def test_from_url_path(self):
        name = self._f({}, 'https://example.com/files/data.csv')
        assert name == 'data.csv'

    def test_trailing_slash_defaults(self):
        name = self._f({}, 'https://example.com/api/')
        assert name == 'api'

    def test_no_path_defaults(self):
        name = self._f({}, 'https://example.com')
        assert name == 'download'

    def test_content_disposition_without_quotes(self):
        name = self._f({'Content-Disposition': 'attachment; filename=notes.txt'},
                       'https://example.com/')
        assert name == 'notes.txt'


# ── Upload: _filename_from_response (existing helper in upload.py) ────────────

class TestFilenameFromResponse:
    def _f(self, headers, url):
        from cli.commands.upload import _filename_from_response
        mock_resp = MagicMock()
        mock_resp.headers = headers
        return _filename_from_response(mock_resp, url)

    def test_from_header(self):
        assert self._f(
            {'Content-Disposition': 'attachment; filename="data.zip"'},
            'https://example.com/'
        ) == 'data.zip'

    def test_from_url(self):
        assert self._f({}, 'https://example.com/path/doc.pdf') == 'doc.pdf'

    def test_fallback(self):
        assert self._f({}, 'https://example.com/') == 'download'


# ── Upload: _fmt_size helper ─────────────────────────────────────────────────

class TestFmtSize:
    def _f(self, n):
        from cli.commands.upload import _fmt_size
        return _fmt_size(n)

    def test_bytes(self):
        assert 'B' in self._f(500)

    def test_kilobytes(self):
        assert 'KB' in self._f(2048)

    def test_megabytes(self):
        assert 'MB' in self._f(5 * 1024 * 1024)

    def test_gigabytes(self):
        assert 'GB' in self._f(2 * 1024 ** 3)


# ── CLI api.upload_from_url ───────────────────────────────────────────────────

class TestUploadFromUrlApi:
    """Test the CLI-side upload_from_url function."""

    def test_success(self):
        from cli.api.file import upload_from_url
        mock_session = MagicMock()
        resp = MagicMock()
        resp.ok = True
        resp.json.return_value = {'key': 'abc', 'filename': 'report.pdf', 'filesize': 1024}
        mock_session.post.return_value = resp
        with patch('cli.api.file.get_csrf', return_value='tok'):
            result = upload_from_url('https://drp.test', mock_session, 'https://example.com/report.pdf')
        assert result == ('abc', 'report.pdf', 1024)

    def test_failure_returns_none(self):
        from cli.api.file import upload_from_url
        mock_session = MagicMock()
        resp = MagicMock()
        resp.ok = False
        resp.status_code = 403
        resp.json.return_value = {'error': 'Paid only'}
        resp.text = 'Paid only'
        mock_session.post.return_value = resp
        with patch('cli.api.file.get_csrf', return_value='tok'):
            with patch('cli.api.file.err'):
                result = upload_from_url('https://drp.test', mock_session, 'https://example.com/file')
        assert result is None

    def test_passes_all_options(self):
        from cli.api.file import upload_from_url
        mock_session = MagicMock()
        resp = MagicMock()
        resp.ok = True
        resp.json.return_value = {'key': 'k', 'filename': 'f', 'filesize': 0}
        mock_session.post.return_value = resp
        with patch('cli.api.file.get_csrf', return_value='tok'):
            upload_from_url(
                'https://drp.test', mock_session, 'https://example.com/f',
                key='mykey', expiry_days=30, password='pw', is_test=True,
                schedule='2h', webhook_url='https://hook.test', notify='7d',
                is_public=True, tags='a,b',
            )
        payload = mock_session.post.call_args.kwargs.get('json') or mock_session.post.call_args[1]['json']
        assert payload['url'] == 'https://example.com/f'
        assert payload['key'] == 'mykey'
        assert payload['expiry_days'] == 30
        assert payload['password'] == 'pw'
        assert payload['is_test'] is True
        assert payload['schedule'] == '2h'
        assert payload['webhook_url'] == 'https://hook.test'
        assert payload['notify'] == '7d'
        assert payload['is_public'] is True
        assert payload['tags'] == 'a,b'


# ── Server-side upload_from_url view ──────────────────────────────────────────

class TestUploadFromUrlView:
    """Django view tests for POST /upload/from-url/."""

    @pytest.fixture(autouse=True)
    def setup_db(self, db):
        """Ensure DB is available."""
        pass

    _user_counter = 0

    def _user(self, plan):
        from django.contrib.auth.models import User
        from core.models import Plan, UserProfile
        TestUploadFromUrlView._user_counter += 1
        u = User.objects.create_user(f'user_{plan}_{self._user_counter}', password='pw')
        UserProfile.objects.filter(user=u).update(plan=plan)
        u.refresh_from_db()
        return u

    def test_requires_post(self):
        from django.test import Client
        c = Client()
        res = c.get('/upload/from-url/')
        assert res.status_code == 405

    def test_requires_login(self):
        import json
        from django.test import Client
        c = Client()
        res = c.post('/upload/from-url/', json.dumps({'url': 'https://example.com/f.pdf'}),
                      content_type='application/json')
        assert res.status_code == 401

    def test_requires_remote_upload_permission(self):
        """Plans without remote_upload=True get 403."""
        import json
        from django.test import Client
        from core.models import Plan
        c = Client()
        for plan in (Plan.FREE, Plan.STARTER):
            u = self._user(plan)
            c.force_login(u)
            res = c.post('/upload/from-url/', json.dumps({'url': 'https://example.com/f.pdf'}),
                          content_type='application/json')
            assert res.status_code == 403, f'{plan} should be blocked'

    def test_rejects_invalid_url(self):
        import json
        from django.test import Client
        from core.models import Plan
        c = Client()
        u = self._user(Plan.PRO)
        c.force_login(u)
        res = c.post('/upload/from-url/', json.dumps({'url': 'ftp://bad'}),
                      content_type='application/json')
        assert res.status_code == 400

    def test_rejects_empty_url(self):
        import json
        from django.test import Client
        from core.models import Plan
        c = Client()
        u = self._user(Plan.PRO)
        c.force_login(u)
        res = c.post('/upload/from-url/', json.dumps({'url': ''}),
                      content_type='application/json')
        assert res.status_code == 400

    @patch('core.views.drops.upload_to_b2')
    @patch('requests.get')
    def test_success_creates_drop(self, mock_get, mock_b2):
        import json
        from django.test import Client
        from core.models import Plan, Drop

        # Mock the remote URL response
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {
            'Content-Type': 'application/pdf',
            'Content-Length': '1024',
            'Content-Disposition': 'attachment; filename="report.pdf"',
        }
        mock_resp.iter_content.return_value = [b'x' * 1024]
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        c = Client()
        u = self._user(Plan.PRO)
        c.force_login(u)
        res = c.post('/upload/from-url/',
                      json.dumps({'url': 'https://example.com/report.pdf', 'key': 'remote-test'}),
                      content_type='application/json')
        assert res.status_code == 200
        data = res.json()
        assert data['key'] == 'remote-test'
        assert data['filename'] == 'report.pdf'
        assert data['filesize'] == 1024
        assert data['new'] is True
        # Drop actually created in DB
        assert Drop.objects.filter(ns='f', key='remote-test').exists()

    @patch('core.views.drops.upload_to_b2')
    @patch('requests.get')
    def test_rejects_localhost_url(self, mock_get, mock_b2):
        import json
        from django.test import Client
        from core.models import Plan
        c = Client()
        u = self._user(Plan.PRO)
        c.force_login(u)
        res = c.post('/upload/from-url/',
                      json.dumps({'url': 'http://localhost/secret'}),
                      content_type='application/json')
        assert res.status_code == 400
        assert 'Blocked' in res.json()['error'] or 'localhost' in res.json()['error']


# ── _parse_expires ────────────────────────────────────────────────────────────

class TestParseExpires:
    def _f(self, v):
        from cli.commands.upload import _parse_expires
        return _parse_expires(v)

    def test_days(self):
        assert self._f('7d') == 7

    def test_years(self):
        assert self._f('1y') == 365

    def test_plain_int(self):
        assert self._f('30') == 30

    def test_none(self):
        assert self._f(None) is None

    def test_empty(self):
        assert self._f('') is None

    def test_invalid(self):
        assert self._f('abc') is None


# ── drp up --remote flag wired to parser ──────────────────────────────────────

class TestRemoteFlag:
    def test_parser_has_remote_flag(self):
        from cli.drp import build_parser
        parser = build_parser()
        args = parser.parse_args(['up', 'https://example.com/file.pdf', '--remote'])
        assert args.remote is True

    def test_parser_remote_default_false(self):
        from cli.drp import build_parser
        parser = build_parser()
        args = parser.parse_args(['up', 'https://example.com/file.pdf'])
        assert args.remote is False


# ── Version check ─────────────────────────────────────────────────────────────

class TestParseVersion:
    def _f(self, v):
        from cli.version_check import _parse_version
        return _parse_version(v)

    def test_simple(self):
        assert self._f('1.2.3') == (1, 2, 3)

    def test_two_part(self):
        assert self._f('0.3') == (0, 3)

    def test_single(self):
        assert self._f('5') == (5,)

    def test_invalid(self):
        assert self._f('abc') == (0,)

    def test_none(self):
        assert self._f(None) == (0,)


class TestIsNewer:
    def _f(self, latest, current):
        from cli.version_check import is_newer
        return is_newer(latest, current)

    def test_newer_patch(self):
        assert self._f('1.0.2', '1.0.1') is True

    def test_newer_minor(self):
        assert self._f('1.1.0', '1.0.9') is True

    def test_newer_major(self):
        assert self._f('2.0.0', '1.9.9') is True

    def test_same(self):
        assert self._f('1.0.0', '1.0.0') is False

    def test_older(self):
        assert self._f('1.0.0', '1.0.1') is False

    def test_two_vs_three(self):
        assert self._f('0.4.0', '0.3') is True

    def test_three_vs_two(self):
        assert self._f('0.3', '0.3.1') is False


class TestShouldCheck:
    def test_no_cache(self):
        from cli.version_check import _should_check
        assert _should_check({}) is True

    def test_recent(self):
        import time
        from cli.version_check import _should_check
        assert _should_check({"last_checked": time.time() - 60}) is False

    def test_stale(self):
        import time
        from cli.version_check import _should_check, CHECK_INTERVAL_HOURS
        stale_time = time.time() - (CHECK_INTERVAL_HOURS * 3600 + 1)
        assert _should_check({"last_checked": stale_time}) is True


class TestCacheReadWrite:
    def test_round_trip(self, tmp_path):
        from cli import version_check
        orig_file = version_check.CACHE_FILE
        try:
            version_check.CACHE_FILE = tmp_path / "vc.json"
            version_check._write_cache("9.8.7")
            data = version_check._read_cache()
            assert data["latest_version"] == "9.8.7"
            assert "last_checked" in data
        finally:
            version_check.CACHE_FILE = orig_file

    def test_read_missing(self, tmp_path):
        from cli import version_check
        orig_file = version_check.CACHE_FILE
        try:
            version_check.CACHE_FILE = tmp_path / "nonexistent.json"
            assert version_check._read_cache() == {}
        finally:
            version_check.CACHE_FILE = orig_file


class TestFetchLatest:
    @patch('requests.get')
    def test_success(self, mock_get):
        from cli.version_check import _fetch_latest
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {"info": {"version": "1.2.3"}}
        mock_get.return_value = mock_resp
        assert _fetch_latest() == "1.2.3"

    @patch('requests.get', side_effect=Exception("network down"))
    def test_network_error(self, mock_get):
        from cli.version_check import _fetch_latest
        assert _fetch_latest() is None

    @patch('requests.get')
    def test_bad_response(self, mock_get):
        from cli.version_check import _fetch_latest
        mock_resp = MagicMock()
        mock_resp.ok = False
        mock_get.return_value = mock_resp
        assert _fetch_latest() is None


class TestVersionChecker:
    @patch('cli.version_check._fetch_latest', return_value='9.9.9')
    @patch('cli.version_check._read_cache', return_value={})
    def test_updates_latest(self, mock_cache, mock_fetch, tmp_path):
        from cli import version_check
        orig_file = version_check.CACHE_FILE
        try:
            version_check.CACHE_FILE = tmp_path / "vc.json"
            checker = version_check.VersionChecker()
            checker._run()
            assert checker.latest == '9.9.9'
        finally:
            version_check.CACHE_FILE = orig_file

    @patch('cli.version_check._fetch_latest')
    def test_uses_cache_when_recent(self, mock_fetch):
        import time
        from cli.version_check import VersionChecker
        with patch('cli.version_check._read_cache', return_value={
            "last_checked": time.time(),
            "latest_version": "2.0.0",
        }):
            checker = VersionChecker()
            checker._run()
            assert checker.latest == "2.0.0"
            mock_fetch.assert_not_called()


class TestStartCheck:
    def test_skipped_when_env_set(self):
        import os
        from cli.version_check import start_check
        os.environ['DRP_NO_UPDATE_CHECK'] = '1'
        try:
            checker = start_check()
            assert checker._thread is None
        finally:
            del os.environ['DRP_NO_UPDATE_CHECK']

    def test_skipped_when_ci(self):
        import os
        from cli.version_check import start_check
        os.environ['CI'] = 'true'
        try:
            checker = start_check()
            assert checker._thread is None
        finally:
            del os.environ['CI']


class TestShowNotice:
    @patch('cli.version_check.__version__', '0.1.0')
    def test_prints_when_newer(self, capsys):
        from cli.version_check import VersionChecker, show_notice
        checker = VersionChecker()
        checker.latest = '9.0.0'
        show_notice(checker)
        out = capsys.readouterr().out
        assert 'update available' in out
        assert '9.0.0' in out
        assert 'pipx upgrade' in out

    @patch('cli.version_check.__version__', '9.0.0')
    def test_silent_when_current(self, capsys):
        from cli.version_check import VersionChecker, show_notice
        checker = VersionChecker()
        checker.latest = '9.0.0'
        show_notice(checker)
        out = capsys.readouterr().out
        assert out == ''

    def test_silent_when_no_data(self, capsys):
        from cli.version_check import VersionChecker, show_notice
        checker = VersionChecker()
        checker.latest = None
        show_notice(checker)
        out = capsys.readouterr().out
        assert out == ''


# ── Download retry ────────────────────────────────────────────────────────────

class TestDownloadRetry:
    """get_file retries on ChunkedEncodingError with Range header."""

    def _mock_session(self, json_data):
        """Session whose .get() returns json_data for the metadata request."""
        resp = MagicMock()
        resp.ok = True
        resp.status_code = 200
        resp.json.return_value = json_data
        sess = MagicMock()
        sess.get.return_value = resp
        return sess

    @patch('cli.api.file._requests')
    def test_retry_resumes_with_range(self, mock_requests):
        """On ChunkedEncodingError, retry sends Range header from bytes downloaded."""
        from cli.api.file import get_file
        import requests as real_requests

        sess = self._mock_session({
            "kind": "file", "filename": "f.bin", "filesize": 100,
            "presigned_url": "https://b2.example.com/f.bin",
        })

        # First attempt: delivers 60 bytes then raises ChunkedEncodingError
        stream1 = MagicMock()
        stream1.__enter__ = MagicMock(return_value=stream1)
        stream1.__exit__ = MagicMock(return_value=False)
        stream1.status_code = 200

        def raise_after_chunks():
            yield b'A' * 60
            raise real_requests.exceptions.ChunkedEncodingError("broken")

        stream1.iter_content.return_value = raise_after_chunks()

        # Second attempt: delivers remaining 40 bytes
        stream2 = MagicMock()
        stream2.__enter__ = MagicMock(return_value=stream2)
        stream2.__exit__ = MagicMock(return_value=False)
        stream2.status_code = 206
        stream2.iter_content.return_value = iter([b'B' * 40])

        mock_requests.get.side_effect = [stream1, stream2]
        mock_requests.exceptions = real_requests.exceptions

        kind, (content, filename) = get_file('https://h', sess, 'k')
        assert kind == 'file'
        assert len(content) == 100
        # Verify the second call included a Range header
        second_call = mock_requests.get.call_args_list[1]
        assert second_call.kwargs.get('headers', {}).get('Range') == 'bytes=60-'

    @patch('cli.api.file._requests')
    def test_retry_exhausted(self, mock_requests):
        """After max retries, returns (None, None)."""
        from cli.api.file import get_file
        import requests as real_requests

        sess = self._mock_session({
            "kind": "file", "filename": "f.bin", "filesize": 100,
            "presigned_url": "https://b2.example.com/f.bin",
        })

        def always_fail(**kwargs):
            raise real_requests.exceptions.ChunkedEncodingError("broken")

        stream = MagicMock()
        stream.__enter__ = MagicMock(return_value=stream)
        stream.__exit__ = MagicMock(return_value=False)
        stream.status_code = 200
        stream.iter_content.side_effect = always_fail

        mock_requests.get.return_value = stream
        mock_requests.exceptions = real_requests.exceptions

        kind, data = get_file('https://h', sess, 'k')
        assert kind is None
        assert data is None


# ── drp lock ──────────────────────────────────────────────────────────────────

class TestLockParser:
    """Parser for drp lock parses all expected flags."""

    def test_lock_basic(self):
        from cli.drp import build_parser
        ns = build_parser().parse_args(['lock', 'mykey'])
        assert ns.command == 'lock'
        assert ns.key == 'mykey'
        assert ns.file is False
        assert ns.remove is False
        assert ns.password is None

    def test_lock_file(self):
        from cli.drp import build_parser
        ns = build_parser().parse_args(['lock', '-f', 'mykey'])
        assert ns.file is True

    def test_lock_remove(self):
        from cli.drp import build_parser
        ns = build_parser().parse_args(['lock', 'mykey', '--remove'])
        assert ns.remove is True

    def test_lock_password_inline(self):
        from cli.drp import build_parser
        ns = build_parser().parse_args(['lock', 'mykey', '--password', 'secret'])
        assert ns.password == 'secret'

    def test_lock_password_prompt_sentinel(self):
        from cli.drp import build_parser
        ns = build_parser().parse_args(['lock', 'mykey', '-p'])
        assert ns.password == '__prompt__'


class TestLockCommand:
    """Mock network tests for cmd_lock."""

    def _make_args(self, key='test', file=False, remove=False, password='pw'):
        a = MagicMock()
        a.key = key
        a.file = file
        a.remove = remove
        a.password = password
        return a

    @patch('cli.commands.lock.Spinner', MagicMock())
    @patch('cli.commands.lock.load_context')
    @patch('cli.api.auth.get_csrf', return_value='tok')
    def test_set_password(self, _csrf, mock_ctx, capsys):
        sess = MagicMock()
        resp = MagicMock(ok=True, status_code=200)
        resp.json.return_value = {'password_protected': True, 'message': 'Password set.'}
        sess.post.return_value = resp
        mock_ctx.return_value = ({}, 'https://h', sess)

        from cli.commands.lock import cmd_lock
        cmd_lock(self._make_args())
        assert 'Password set' in capsys.readouterr().out

    @patch('cli.commands.lock.Spinner', MagicMock())
    @patch('cli.commands.lock.load_context')
    @patch('cli.api.auth.get_csrf', return_value='tok')
    def test_remove_password(self, _csrf, mock_ctx, capsys):
        sess = MagicMock()
        resp = MagicMock(ok=True, status_code=200)
        resp.json.return_value = {'password_protected': False, 'message': 'Password removed.'}
        sess.post.return_value = resp
        mock_ctx.return_value = ({}, 'https://h', sess)

        from cli.commands.lock import cmd_lock
        cmd_lock(self._make_args(remove=True, password=None))
        assert 'Password removed' in capsys.readouterr().out

    @patch('cli.commands.lock.Spinner', MagicMock())
    @patch('cli.commands.lock.load_context')
    @patch('cli.api.auth.get_csrf', return_value='tok')
    def test_file_drop_url(self, _csrf, mock_ctx, capsys):
        sess = MagicMock()
        resp = MagicMock(ok=True, status_code=200)
        resp.json.return_value = {'message': 'Password set.'}
        sess.post.return_value = resp
        mock_ctx.return_value = ({}, 'https://h', sess)

        from cli.commands.lock import cmd_lock
        cmd_lock(self._make_args(key='fkey', file=True))
        url_used = sess.post.call_args[0][0]
        assert '/f/fkey/set-password/' in url_used

    @patch('cli.commands.lock.Spinner', MagicMock())
    @patch('cli.commands.lock.load_context')
    @patch('cli.api.auth.get_csrf', return_value='tok')
    def test_text_drop_url(self, _csrf, mock_ctx, capsys):
        sess = MagicMock()
        resp = MagicMock(ok=True, status_code=200)
        resp.json.return_value = {'message': 'Password set.'}
        sess.post.return_value = resp
        mock_ctx.return_value = ({}, 'https://h', sess)

        from cli.commands.lock import cmd_lock
        cmd_lock(self._make_args(key='tkey', file=False))
        url_used = sess.post.call_args[0][0]
        assert '/tkey/set-password/' in url_used
        assert '/f/' not in url_used

    @patch('cli.commands.lock.Spinner', MagicMock())
    @patch('cli.commands.lock.load_context')
    @patch('cli.api.auth.get_csrf', return_value='tok')
    def test_403_paid_feature(self, _csrf, mock_ctx, capsys):
        sess = MagicMock()
        resp = MagicMock(ok=False, status_code=403)
        resp.json.return_value = {'error': 'Password protection is a paid feature.'}
        sess.post.return_value = resp
        mock_ctx.return_value = ({}, 'https://h', sess)

        from cli.commands.lock import cmd_lock
        with pytest.raises(SystemExit):
            cmd_lock(self._make_args())
        assert 'paid feature' in capsys.readouterr().err

    @patch('cli.commands.lock.Spinner', MagicMock())
    @patch('cli.commands.lock.load_context')
    @patch('cli.api.auth.get_csrf', return_value='tok')
    def test_404_not_found(self, _csrf, mock_ctx, capsys):
        sess = MagicMock()
        resp = MagicMock(ok=False, status_code=404)
        resp.json.return_value = {}
        sess.post.return_value = resp
        mock_ctx.return_value = ({}, 'https://h', sess)

        from cli.commands.lock import cmd_lock
        with pytest.raises(SystemExit):
            cmd_lock(self._make_args())
        assert 'not found' in capsys.readouterr().err


# ── drp ask ───────────────────────────────────────────────────────────────────

class TestAsk:
    """Tests for ask command basics."""

    def test_ask_clear_parser_flag(self):
        from cli.drp import build_parser
        ns = build_parser().parse_args(['ask', '--clear'])
        assert ns.clear is True
        assert ns.question is None

    @patch('cli.commands.ask.load_context')
    def test_cmd_ask_clear(self, mock_ctx, capsys):
        mock_session = MagicMock()
        mock_ctx.return_value = ({}, 'https://test.drp.fyi', mock_session)
        from cli.commands.ask import cmd_ask
        args = MagicMock()
        args.history = False
        args.clear = True
        cmd_ask(args)
        out = capsys.readouterr().out
        assert 'cleared' in out
        mock_session.delete.assert_called_once()


# ── Live reference edge cases ─────────────────────────────────────────────────

class TestLiveRefGetClipboard:
    """get_clipboard handling of live reference responses."""

    def test_live_error_returned(self):
        from cli.api.text import get_clipboard
        mock_session = MagicMock()
        mock_resp = MagicMock(ok=True, status_code=200)
        mock_resp.json.return_value = {
            'kind': 'text',
            'source_url': 'https://api.example.com/status',
            'content': 'https://api.example.com/status',
            'fetch_error': '404 Client Error: Not Found',
        }
        mock_session.get.return_value = mock_resp
        kind, data = get_clipboard('https://h', mock_session, 'status')
        assert kind == 'live_error'
        assert data['fetch_error'] == '404 Client Error: Not Found'
        assert data['source_url'] == 'https://api.example.com/status'

    def test_binary_ref_returned(self):
        from cli.api.text import get_clipboard
        mock_session = MagicMock()
        mock_resp = MagicMock(ok=True, status_code=200)
        mock_resp.json.return_value = {
            'kind': 'text',
            'source_url': 'https://example.com/file.zip',
            'content': 'https://example.com/file.zip',
            'binary': True,
            'content_type': 'application/zip',
        }
        mock_session.get.return_value = mock_resp
        kind, data = get_clipboard('https://h', mock_session, 'zkey')
        assert kind == 'binary_ref'
        assert data['content_type'] == 'application/zip'

    def test_successful_live_ref(self):
        from cli.api.text import get_clipboard
        mock_session = MagicMock()
        mock_resp = MagicMock(ok=True, status_code=200)
        mock_resp.json.return_value = {
            'kind': 'text',
            'source_url': 'https://api.example.com/data',
            'content': '{"status": "ok"}',
        }
        mock_session.get.return_value = mock_resp
        kind, content = get_clipboard('https://h', mock_session, 'api')
        assert kind == 'text'
        assert content == '{"status": "ok"}'


class TestLiveRefGetCommand:
    """_get_clipboard handling of live_error and binary_ref."""

    @patch('cli.commands.get.api')
    @patch('cli.commands.get.load_context')
    def test_live_error_shows_message(self, mock_ctx, mock_api, capsys):
        mock_ctx.return_value = ({}, 'https://h', MagicMock())
        mock_api.get_clipboard.return_value = ('live_error', {
            'source_url': 'https://api.example.com/broken',
            'fetch_error': '503 Server Error',
        })
        args = MagicMock()
        args.key = 'broken'
        args.file = False
        args.clip = False
        args.timing = False
        args.url = False
        args.password = None
        args.parse = False
        args.field = None
        with pytest.raises(SystemExit):
            from cli.commands.get import cmd_get
            cmd_get(args)
        err = capsys.readouterr().err
        assert 'fetch failed' in err
        assert 'api.example.com/broken' in err
        assert '503' in err

    @patch('cli.commands.get.api')
    @patch('cli.commands.get.load_context')
    def test_binary_ref_shows_tip(self, mock_ctx, mock_api, capsys):
        mock_ctx.return_value = ({}, 'https://h', MagicMock())
        mock_api.get_clipboard.return_value = ('binary_ref', {
            'source_url': 'https://example.com/data.zip',
            'content_type': 'application/zip',
            'content_length': 5000,
        })
        args = MagicMock()
        args.key = 'zippy'
        args.file = False
        args.clip = False
        args.timing = False
        args.url = False
        args.password = None
        args.parse = False
        args.field = None
        from cli.commands.get import cmd_get
        cmd_get(args)
        out = capsys.readouterr().out
        assert 'binary content' in out
        assert 'application/zip' in out
        assert '5,000' in out
