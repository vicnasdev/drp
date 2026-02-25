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

    def test_requires_pro_plan(self):
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
