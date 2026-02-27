"""
Tests for cli/api/actions.py — API action functions.

Mocks HTTP responses to test error handling, return values, and edge cases.
"""

import pytest
from unittest.mock import patch, MagicMock

from cli.api.actions import (
    delete, rename, renew, save_bookmark,
    copy_drop, lock_drop, create_folder,
    key_exists, list_drops,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mock_session(status=200, json_data=None, text=''):
    s = MagicMock()
    resp = MagicMock()
    resp.ok = 200 <= status < 400
    resp.status_code = status
    resp.json.return_value = json_data or {}
    resp.text = text
    s.post.return_value = resp
    s.delete.return_value = resp
    s.get.return_value = resp
    return s


@pytest.fixture(autouse=True)
def _mock_csrf():
    with patch('cli.api.actions.get_csrf', return_value='csrf-token'):
        yield


# ── delete ────────────────────────────────────────────────────────────────────

class TestDelete:
    def test_delete_success(self):
        session = _mock_session(200)
        assert delete('https://drp.test', session, 'mykey') is True

    def test_delete_404(self):
        session = _mock_session(404)
        assert delete('https://drp.test', session, 'mykey') is False

    def test_delete_network_error(self):
        session = MagicMock()
        session.delete.side_effect = Exception('timeout')
        with patch('cli.api.actions.get_csrf', return_value='csrf'):
            assert delete('https://drp.test', session, 'mykey') is False


# ── rename ────────────────────────────────────────────────────────────────────

class TestRename:
    def test_rename_success(self):
        session = _mock_session(200, {'key': 'newkey'})
        assert rename('https://drp.test', session, 'old', 'newkey') == 'newkey'

    def test_rename_404(self):
        session = _mock_session(404)
        assert rename('https://drp.test', session, 'old', 'new') is False

    def test_rename_409_conflict(self):
        session = _mock_session(409)
        assert rename('https://drp.test', session, 'old', 'taken') is False

    def test_rename_403(self):
        session = _mock_session(403, {'error': 'locked'})
        assert rename('https://drp.test', session, 'old', 'new') is False

    def test_rename_400(self):
        session = _mock_session(400, {'error': 'bad key'})
        assert rename('https://drp.test', session, 'old', 'bad!') is False

    def test_rename_network_error(self):
        session = MagicMock()
        session.post.side_effect = Exception('timeout')
        with patch('cli.api.actions.get_csrf', return_value='csrf'):
            assert rename('https://drp.test', session, 'a', 'b') is None


# ── renew ─────────────────────────────────────────────────────────────────────

class TestRenew:
    def test_renew_success(self):
        session = _mock_session(200, {'expires_at': '2025-12-31T00:00:00Z', 'renewals': 2})
        assert renew('https://drp.test', session, 'k') == ('2025-12-31T00:00:00Z', 2)

    def test_renew_failure(self):
        session = _mock_session(403)
        assert renew('https://drp.test', session, 'k') == (None, None)


# ── copy_drop ─────────────────────────────────────────────────────────────────

class TestCopyDrop:
    def test_copy_success(self):
        session = _mock_session(200, {'key': 'notes-copy'})
        assert copy_drop('https://drp.test', session, 'notes', 'notes-copy') == 'notes-copy'

    def test_copy_auto_key(self):
        session = _mock_session(200, {'key': 'notes-1'})
        assert copy_drop('https://drp.test', session, 'notes') == 'notes-1'

    def test_copy_404(self):
        session = _mock_session(404)
        assert copy_drop('https://drp.test', session, 'x') is False

    def test_copy_409(self):
        session = _mock_session(409)
        assert copy_drop('https://drp.test', session, 'x', 'taken') is False

    def test_copy_403(self):
        session = _mock_session(403, {'error': 'locked'})
        assert copy_drop('https://drp.test', session, 'x') is False

    def test_copy_network_error(self):
        session = MagicMock()
        session.post.side_effect = Exception('timeout')
        with patch('cli.api.actions.get_csrf', return_value='csrf'):
            assert copy_drop('https://drp.test', session, 'x') is None


# ── lock_drop ─────────────────────────────────────────────────────────────────

class TestLockDrop:
    def test_lock_set_password(self):
        session = _mock_session(200)
        assert lock_drop('https://drp.test', session, 'k', password='pw') is True

    def test_lock_remove(self):
        session = _mock_session(200)
        assert lock_drop('https://drp.test', session, 'k', remove=True) is True

    def test_lock_404(self):
        session = _mock_session(404)
        assert lock_drop('https://drp.test', session, 'k', password='pw') is False

    def test_lock_403_requires_paid(self):
        session = _mock_session(403)
        assert lock_drop('https://drp.test', session, 'k', password='pw') is False

    def test_lock_network_error(self):
        session = MagicMock()
        session.post.side_effect = Exception('timeout')
        with patch('cli.api.actions.get_csrf', return_value='csrf'):
            assert lock_drop('https://drp.test', session, 'k', password='pw') is False


# ── create_folder ─────────────────────────────────────────────────────────────

class TestCreateFolder:
    def test_create_success(self):
        session = _mock_session(201, {'slug': 'docs', 'name': 'Documents'})
        result = create_folder('https://drp.test', session, 'Documents')
        assert result == {'slug': 'docs', 'name': 'Documents'}

    def test_create_with_parent(self):
        session = _mock_session(201, {'slug': 'sub', 'name': 'Sub'})
        result = create_folder('https://drp.test', session, 'Sub', parent_id=42)
        assert result is not None
        # Verify the post payload includes parent_id
        call_kwargs = session.post.call_args
        import json
        body = json.loads(call_kwargs[1].get('data', call_kwargs[0][1] if len(call_kwargs[0]) > 1 else '{}'))
        assert body.get('parent_id') == 42

    def test_create_409_exists(self):
        session = _mock_session(409)
        assert create_folder('https://drp.test', session, 'docs') is None

    def test_create_network_error(self):
        session = MagicMock()
        session.post.side_effect = Exception('timeout')
        with patch('cli.api.actions.get_csrf', return_value='csrf'):
            assert create_folder('https://drp.test', session, 'docs') is None


# ── save_bookmark ─────────────────────────────────────────────────────────────

class TestSaveBookmark:
    def test_save_success(self):
        session = _mock_session(200)
        assert save_bookmark('https://drp.test', session, 'k') is True

    def test_save_redirect_means_not_logged_in(self):
        session = _mock_session(302)
        assert save_bookmark('https://drp.test', session, 'k') is False

    def test_save_404(self):
        session = _mock_session(404)
        assert save_bookmark('https://drp.test', session, 'k') is False

    def test_save_403(self):
        session = _mock_session(403)
        assert save_bookmark('https://drp.test', session, 'k') is False


# ── key_exists ────────────────────────────────────────────────────────────────

class TestKeyExists:
    def test_exists_true(self):
        session = _mock_session(200, {'available': False})
        assert key_exists('https://drp.test', session, 'taken') is True

    def test_exists_false(self):
        session = _mock_session(200, {'available': True})
        assert key_exists('https://drp.test', session, 'free') is False

    def test_exists_network_error(self):
        session = MagicMock()
        session.get.side_effect = Exception('timeout')
        assert key_exists('https://drp.test', session, 'k') is False


# ── list_drops ────────────────────────────────────────────────────────────────

class TestListDrops:
    def test_list_success(self):
        session = _mock_session(200, {'drops': [{'key': 'a'}, {'key': 'b'}]})
        result = list_drops('https://drp.test', session)
        assert len(result) == 2

    def test_list_redirect(self):
        """302 with ok=True returns empty list from json; ok=False returns None."""
        session = _mock_session(302)
        # ok is True for 302 (200 <= 302 < 400), so json branch runs
        assert list_drops('https://drp.test', session) == []

    def test_list_forbidden(self):
        """403 is not ok, so falls through to status_code check → None."""
        s = MagicMock()
        resp = MagicMock()
        resp.ok = False
        resp.status_code = 403
        s.get.return_value = resp
        assert list_drops('https://drp.test', s) is None
