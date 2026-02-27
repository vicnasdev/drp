"""
Tests for CLI manage commands: rm, mv, cp, renew, save, lock, mkdir.

All API calls are mocked — these are pure unit tests that verify:
  • Arguments are forwarded correctly to the API layer
  • Success/failure output and exit codes are correct
  • Local config is updated on success
"""

import pytest
from unittest.mock import patch, MagicMock
from types import SimpleNamespace

from cli.commands.manage import (
    cmd_rm, cmd_mv, cmd_renew, cmd_cp, cmd_save, cmd_lock, cmd_mkdir,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fake_context(**overrides):
    """Patch load_context to return (cfg, host, session)."""
    cfg = overrides.get('cfg', {'host': 'https://drp.test', 'username': 'alice'})
    host = overrides.get('host', 'https://drp.test')
    session = overrides.get('session', MagicMock())
    return patch('cli.commands.manage.load_context', return_value=(cfg, host, session))


# ── cmd_rm ────────────────────────────────────────────────────────────────────

class TestCmdRm:
    def test_rm_success(self, capsys):
        args = SimpleNamespace(key='notes')
        with _fake_context(), \
             patch('cli.commands.manage.api') as mock_api, \
             patch('cli.commands.manage.config') as mock_config:
            mock_api.delete.return_value = True
            cmd_rm(args)
        out = capsys.readouterr().out
        assert '✓' in out
        assert 'notes' in out
        mock_config.remove_local_drop.assert_called_once_with('notes')

    def test_rm_failure_exits(self, capsys):
        args = SimpleNamespace(key='gone')
        with _fake_context(), \
             patch('cli.commands.manage.api') as mock_api, \
             patch('cli.commands.manage.config'), \
             patch('cli.commands.manage.report_outcome'), \
             pytest.raises(SystemExit):
            mock_api.delete.return_value = False
            cmd_rm(args)


# ── cmd_mv ────────────────────────────────────────────────────────────────────

class TestCmdMv:
    def test_mv_success(self, capsys):
        args = SimpleNamespace(key='old', new_key='new')
        with _fake_context(), \
             patch('cli.commands.manage.api') as mock_api, \
             patch('cli.commands.manage.config') as mock_config:
            mock_api.rename.return_value = 'new'
            cmd_mv(args)
        out = capsys.readouterr().out
        assert 'old' in out
        assert 'new' in out
        mock_config.rename_local_drop.assert_called_once_with('old', 'new')

    def test_mv_conflict_exits(self, capsys):
        args = SimpleNamespace(key='x', new_key='taken')
        with _fake_context(), \
             patch('cli.commands.manage.api') as mock_api, \
             patch('cli.commands.manage.config'), \
             patch('cli.commands.manage.report_outcome'), \
             pytest.raises(SystemExit):
            mock_api.rename.return_value = False
            cmd_mv(args)

    def test_mv_unexpected_error_exits(self, capsys):
        args = SimpleNamespace(key='x', new_key='y')
        with _fake_context(), \
             patch('cli.commands.manage.api') as mock_api, \
             patch('cli.commands.manage.config'), \
             patch('cli.commands.manage.report_outcome'), \
             pytest.raises(SystemExit):
            mock_api.rename.return_value = None
            cmd_mv(args)


# ── cmd_cp ────────────────────────────────────────────────────────────────────

class TestCmdCp:
    def test_cp_success(self, capsys):
        args = SimpleNamespace(key='src', new_key='dst')
        with _fake_context(), \
             patch('cli.commands.manage.api') as mock_api, \
             patch('cli.commands.manage.config') as mock_config:
            mock_api.copy_drop.return_value = 'dst'
            cmd_cp(args)
        out = capsys.readouterr().out
        assert 'src' in out
        assert 'dst' in out
        mock_config.record_drop.assert_called_once()

    def test_cp_no_new_key(self, capsys):
        args = SimpleNamespace(key='src', new_key=None)
        with _fake_context(), \
             patch('cli.commands.manage.api') as mock_api, \
             patch('cli.commands.manage.config'):
            mock_api.copy_drop.return_value = 'src-copy'
            cmd_cp(args)
        out = capsys.readouterr().out
        assert 'src-copy' in out

    def test_cp_failure_exits(self):
        args = SimpleNamespace(key='src', new_key='x')
        with _fake_context(), \
             patch('cli.commands.manage.api') as mock_api, \
             patch('cli.commands.manage.config'), \
             patch('cli.commands.manage.report_outcome'), \
             pytest.raises(SystemExit):
            mock_api.copy_drop.return_value = None
            cmd_cp(args)

    def test_cp_local_file_uploads(self, capsys, tmp_path, monkeypatch):
        """drp cp file1.txt → file exists → upload instead of server copy."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / 'file1.txt').write_text('hello')
        args = SimpleNamespace(key='file1.txt', new_key=None)
        with _fake_context(), \
             patch('cli.commands.manage.api') as mock_api, \
             patch('cli.commands.manage.config'):
            mock_api.upload_file.return_value = 'abc-123'
            cmd_cp(args)
        out = capsys.readouterr().out
        assert '✓' in out
        assert 'abc-123' in out
        mock_api.upload_file.assert_called_once()
        # Should NOT call copy_drop
        mock_api.copy_drop.assert_not_called()

    def test_cp_local_file_not_exists_does_server_copy(self, capsys, tmp_path, monkeypatch):
        """drp cp nonexistent → no file → server-side copy."""
        monkeypatch.chdir(tmp_path)
        args = SimpleNamespace(key='nonexistent', new_key=None)
        with _fake_context(), \
             patch('cli.commands.manage.api') as mock_api, \
             patch('cli.commands.manage.config'):
            mock_api.copy_drop.return_value = 'nonexistent-1'
            cmd_cp(args)
        out = capsys.readouterr().out
        assert 'nonexistent-1' in out
        mock_api.upload_file.assert_not_called()

    def test_cp_local_file_upload_failure_exits(self, tmp_path, monkeypatch):
        """drp cp file.txt → upload fails → exit 1."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / 'file.txt').write_text('data')
        args = SimpleNamespace(key='file.txt', new_key=None)
        with _fake_context(), \
             patch('cli.commands.manage.api') as mock_api, \
             patch('cli.commands.manage.config'), \
             pytest.raises(SystemExit):
            mock_api.upload_file.return_value = None
            cmd_cp(args)


# ── cmd_renew ─────────────────────────────────────────────────────────────────

class TestCmdRenew:
    def test_renew_success(self, capsys):
        args = SimpleNamespace(key='notes')
        with _fake_context(), \
             patch('cli.commands.manage.api') as mock_api:
            mock_api.renew.return_value = ('2025-12-31T00:00:00Z', 3)
            cmd_renew(args)
        out = capsys.readouterr().out
        assert '✓' in out
        assert 'notes' in out

    def test_renew_failure_exits(self):
        args = SimpleNamespace(key='notes')
        with _fake_context(), \
             patch('cli.commands.manage.api') as mock_api, \
             patch('cli.commands.manage.report_outcome'), \
             pytest.raises(SystemExit):
            mock_api.renew.return_value = (None, None)
            cmd_renew(args)


# ── cmd_save ──────────────────────────────────────────────────────────────────

class TestCmdSave:
    def test_save_success(self, capsys):
        args = SimpleNamespace(key='notes')
        with _fake_context(), \
             patch('cli.commands.manage.api') as mock_api:
            mock_api.save_bookmark.return_value = True
            cmd_save(args)
        out = capsys.readouterr().out
        assert '✓' in out
        assert 'Bookmarked' in out

    def test_save_failure_exits(self):
        args = SimpleNamespace(key='notes')
        with _fake_context(), \
             patch('cli.commands.manage.api') as mock_api, \
             pytest.raises(SystemExit):
            mock_api.save_bookmark.return_value = False
            cmd_save(args)


# ── cmd_lock ──────────────────────────────────────────────────────────────────

class TestCmdLock:
    def test_lock_set_password(self, capsys):
        args = SimpleNamespace(key='notes', password='secret', remove=False)
        with _fake_context(), \
             patch('cli.commands.manage.api') as mock_api:
            mock_api.lock_drop.return_value = True
            cmd_lock(args)
        out = capsys.readouterr().out
        assert 'password-protected' in out

    def test_lock_remove_password(self, capsys):
        args = SimpleNamespace(key='notes', password=None, remove=True)
        with _fake_context(), \
             patch('cli.commands.manage.api') as mock_api:
            mock_api.lock_drop.return_value = True
            cmd_lock(args)
        out = capsys.readouterr().out
        assert 'removed' in out

    def test_lock_set_failure_exits(self):
        args = SimpleNamespace(key='notes', password='pw', remove=False)
        with _fake_context(), \
             patch('cli.commands.manage.api') as mock_api, \
             pytest.raises(SystemExit):
            mock_api.lock_drop.return_value = False
            cmd_lock(args)


# ── cmd_mkdir ─────────────────────────────────────────────────────────────────

class TestCmdMkdir:
    def test_mkdir_success(self, capsys):
        args = SimpleNamespace(name='docs', parent=None)
        with _fake_context(), \
             patch('cli.commands.manage.api') as mock_api:
            mock_api.create_folder.return_value = {'slug': 'docs', 'name': 'docs'}
            cmd_mkdir(args)
        out = capsys.readouterr().out
        assert '✓' in out
        assert 'docs' in out

    def test_mkdir_failure_exits(self):
        args = SimpleNamespace(name='docs', parent=None)
        with _fake_context(), \
             patch('cli.commands.manage.api') as mock_api, \
             pytest.raises(SystemExit):
            mock_api.create_folder.return_value = None
            cmd_mkdir(args)

    def test_mkdir_with_parent(self, capsys):
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {'id': 42}
        mock_session.get.return_value = mock_response

        args = SimpleNamespace(name='sub', parent='docs')
        with _fake_context(session=mock_session), \
             patch('cli.commands.manage.api') as mock_api:
            mock_api.create_folder.return_value = {'slug': 'sub', 'name': 'sub'}
            cmd_mkdir(args)
        mock_api.create_folder.assert_called_once_with(
            'https://drp.test', mock_session, 'sub', parent_id=42
        )
