"""
Tests for ResilientSession — retry logic with exponential backoff.

Uses mocks to simulate transient failures and verify retry behavior
without actually sleeping or hitting a network.
"""

import pytest
from unittest.mock import patch, MagicMock, call

from cli.session import (
    ResilientSession, RETRY_BACKOFF, RETRY_STATUS_CODES,
    SESSION_CACHE_SECS,
)
import requests


# ── Retry on status codes ────────────────────────────────────────────────────

class TestRetryOnStatus:
    @patch('time.sleep')
    def test_retries_on_502(self, mock_sleep):
        session = ResilientSession()
        responses = [
            MagicMock(status_code=502),
            MagicMock(status_code=200),
        ]
        with patch.object(requests.Session, 'request', side_effect=responses):
            resp = session.request('GET', 'https://drp.test/api/')
        assert resp.status_code == 200
        assert mock_sleep.called

    @patch('time.sleep')
    def test_retries_on_503(self, mock_sleep):
        session = ResilientSession()
        responses = [
            MagicMock(status_code=503),
            MagicMock(status_code=200),
        ]
        with patch.object(requests.Session, 'request', side_effect=responses):
            resp = session.request('GET', 'https://drp.test/api/')
        assert resp.status_code == 200

    @patch('time.sleep')
    def test_retries_on_504(self, mock_sleep):
        session = ResilientSession()
        responses = [
            MagicMock(status_code=504),
            MagicMock(status_code=200),
        ]
        with patch.object(requests.Session, 'request', side_effect=responses):
            resp = session.request('GET', 'https://drp.test/api/')
        assert resp.status_code == 200

    @patch('time.sleep')
    def test_does_not_retry_on_404(self, mock_sleep):
        session = ResilientSession()
        with patch.object(requests.Session, 'request',
                          return_value=MagicMock(status_code=404)):
            resp = session.request('GET', 'https://drp.test/api/')
        assert resp.status_code == 404
        mock_sleep.assert_not_called()

    @patch('time.sleep')
    def test_does_not_retry_on_401(self, mock_sleep):
        session = ResilientSession()
        with patch.object(requests.Session, 'request',
                          return_value=MagicMock(status_code=401)):
            resp = session.request('GET', 'https://drp.test/api/')
        assert resp.status_code == 401
        mock_sleep.assert_not_called()


# ── Retry on exceptions ──────────────────────────────────────────────────────

class TestRetryOnException:
    @patch('time.sleep')
    def test_retries_on_connection_error(self, mock_sleep):
        session = ResilientSession()
        effects = [
            requests.exceptions.ConnectionError('refused'),
            MagicMock(status_code=200),
        ]
        with patch.object(requests.Session, 'request', side_effect=effects):
            resp = session.request('GET', 'https://drp.test/')
        assert resp.status_code == 200

    @patch('time.sleep')
    def test_retries_on_timeout(self, mock_sleep):
        session = ResilientSession()
        effects = [
            requests.exceptions.Timeout('timed out'),
            MagicMock(status_code=200),
        ]
        with patch.object(requests.Session, 'request', side_effect=effects):
            resp = session.request('GET', 'https://drp.test/')
        assert resp.status_code == 200

    @patch('time.sleep')
    def test_raises_after_exhausting_retries(self, mock_sleep):
        session = ResilientSession()
        exc = requests.exceptions.ConnectionError('down')
        with patch.object(requests.Session, 'request', side_effect=exc):
            with pytest.raises(requests.exceptions.ConnectionError):
                session.request('GET', 'https://drp.test/')

    @patch('time.sleep')
    def test_non_retriable_exception_propagates_immediately(self, mock_sleep):
        session = ResilientSession()
        with patch.object(requests.Session, 'request',
                          side_effect=ValueError('bad')):
            with pytest.raises(ValueError):
                session.request('GET', 'https://drp.test/')
        mock_sleep.assert_not_called()


# ── Backoff timing ────────────────────────────────────────────────────────────

class TestBackoffTiming:
    @patch('time.sleep')
    def test_backoff_sequence_length(self, mock_sleep):
        """7 retries + 1 initial = 8 total attempts."""
        assert len(RETRY_BACKOFF) == 7

    @patch('time.sleep')
    def test_first_retry_waits_1_second(self, mock_sleep):
        session = ResilientSession()
        effects = [
            MagicMock(status_code=502),
            MagicMock(status_code=200),
        ]
        with patch.object(requests.Session, 'request', side_effect=effects):
            session.request('GET', 'https://drp.test/')
        mock_sleep.assert_called_with(RETRY_BACKOFF[0])

    def test_total_budget_about_120s(self):
        assert 110 <= sum(RETRY_BACKOFF) <= 130

    def test_retry_status_codes_are_server_errors(self):
        for code in RETRY_STATUS_CODES:
            assert 500 <= code <= 599


# ── Constants ─────────────────────────────────────────────────────────────────

class TestConstants:
    def test_session_cache_is_one_hour(self):
        assert SESSION_CACHE_SECS == 3600

    def test_retry_codes_frozen(self):
        assert isinstance(RETRY_STATUS_CODES, frozenset)


# ══════════════════════════════════════════════════════════════════════════════
# _first_csrf — CSRF cookie preference logic
# ══════════════════════════════════════════════════════════════════════════════

class TestFirstCsrf:
    """_first_csrf should prefer domain-set cookies over bare ones."""

    def test_bare_cookie_returned(self):
        """When only a bare cookie exists, return it."""
        from cli.api.auth import _first_csrf
        session = ResilientSession()
        session.cookies.set('csrftoken', 'bare-value')
        assert _first_csrf(session) == 'bare-value'

    def test_domain_cookie_preferred(self):
        """When both bare and domain-set cookies exist, prefer domain."""
        from cli.api.auth import _first_csrf
        session = ResilientSession()
        # Bare cookie (from JSON load — no domain metadata)
        session.cookies.set('csrftoken', 'old-value')
        # Domain-set cookie (from server Set-Cookie header)
        session.cookies.set('csrftoken', 'new-value', domain='.drp.fyi')
        assert _first_csrf(session) == 'new-value'

    def test_only_domain_cookie(self):
        """When only a domain cookie exists, return it."""
        from cli.api.auth import _first_csrf
        session = ResilientSession()
        session.cookies.set('csrftoken', 'srv', domain='.drp.fyi')
        assert _first_csrf(session) == 'srv'

    def test_no_csrf_cookie_returns_none(self):
        from cli.api.auth import _first_csrf
        session = ResilientSession()
        assert _first_csrf(session) is None


# ══════════════════════════════════════════════════════════════════════════════
# load_context — Referer header
# ══════════════════════════════════════════════════════════════════════════════

class TestLoadContextReferer:
    """load_context should set Referer header on the session."""

    def test_referer_set(self):
        from cli.commands._context import load_context
        with patch('cli.commands._context.config') as mock_config, \
             patch('cli.commands._context.auto_login', return_value=True):
            mock_config.load.return_value = {
                'host': 'https://dev.drp.fyi',
                'email': 'a@b.com',
            }
            mock_config.CONFIG_DIR = MagicMock()
            cfg, host, session = load_context()
        assert session.headers.get('Referer') == 'https://dev.drp.fyi/'
