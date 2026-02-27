"""
Tests for the drp shell _dispatch function.

Verifies that all inline shell commands (rm, cp, mv, save, renew, lock, mkdir,
info, rekey, cat, add, open, link) work correctly with mocked API calls.
"""

import pytest
from unittest.mock import patch, MagicMock

from cli.commands.shell import _dispatch, _NOT_HANDLED


HOST = 'https://drp.test'
USER = 'alice'

def _cfg():
    return {'host': HOST, 'username': USER}


def _session_ok(json_data=None):
    s = MagicMock()
    r = MagicMock()
    r.ok = True
    r.status_code = 200
    r.json.return_value = json_data or {}
    s.get.return_value = r
    s.post.return_value = r
    s.delete.return_value = r
    return s


def _session_err(status=404):
    s = MagicMock()
    r = MagicMock()
    r.ok = False
    r.status_code = status
    r.json.return_value = {}
    r.text = 'error'
    s.get.return_value = r
    s.post.return_value = r
    s.delete.return_value = r
    return s


# ── rm ────────────────────────────────────────────────────────────────────────

class TestShellRm:
    def test_rm_no_args(self):
        lines = _dispatch('rm', [], HOST, _session_ok(), _cfg(), None, USER)
        assert any('Usage' in l for l in lines)

    def test_rm_success(self):
        with patch('cli.api.actions.get_csrf', return_value='c'), \
             patch('cli.api.actions.delete', return_value=True):
            lines = _dispatch('rm', ['mykey'], HOST, _session_ok(), _cfg(), None, USER)
        assert any('✓' in l for l in lines)

    def test_rm_failure(self):
        with patch('cli.api.actions.get_csrf', return_value='c'), \
             patch('cli.api.actions.delete', return_value=False):
            lines = _dispatch('rm', ['mykey'], HOST, _session_ok(), _cfg(), None, USER)
        assert any('✗' in l for l in lines)


# ── cp ────────────────────────────────────────────────────────────────────────

class TestShellCp:
    def test_cp_no_args(self):
        lines = _dispatch('cp', [], HOST, _session_ok(), _cfg(), None, USER)
        assert any('Usage' in l for l in lines)

    def test_cp_success(self):
        with patch('cli.api.actions.get_csrf', return_value='c'), \
             patch('cli.api.actions.copy_drop', return_value='dst'), \
             patch('cli.config.record_drop'):
            lines = _dispatch('cp', ['src', 'dst'], HOST, _session_ok(), _cfg(), None, USER)
        assert any('✓' in l for l in lines)
        assert any('dst' in l for l in lines)

    def test_cp_no_new_key(self):
        with patch('cli.api.actions.get_csrf', return_value='c'), \
             patch('cli.api.actions.copy_drop', return_value='src-1'), \
             patch('cli.config.record_drop'):
            lines = _dispatch('cp', ['src'], HOST, _session_ok(), _cfg(), None, USER)
        assert any('src-1' in l for l in lines)

    def test_cp_local_file_upload(self, tmp_path):
        """cp ./some_file . should upload the local file."""
        f = tmp_path / 'test.txt'
        f.write_text('hello')
        with patch('cli.api.file.upload_file', return_value='test-abc') as mock_up, \
             patch('cli.config.record_drop'):
            lines = _dispatch('cp', [str(f), '.'], HOST, _session_ok(), _cfg(), None, USER)
        assert any('✓' in l for l in lines)
        assert any('test-abc' in l for l in lines)
        mock_up.assert_called_once()

    def test_cp_local_dotslash(self, tmp_path):
        """cp ./foo.txt should detect as local path."""
        f = tmp_path / 'foo.txt'
        f.write_text('data')
        with patch('cli.api.file.upload_file', return_value='foo-xyz') as mock_up, \
             patch('cli.config.record_drop'):
            lines = _dispatch('cp', [str(f)], HOST, _session_ok(), _cfg(), None, USER)
        assert any('✓' in l for l in lines)

    def test_cp_local_missing_file(self):
        """cp /nonexistent/path should say file not found."""
        lines = _dispatch('cp', ['/nonexistent/no-such-file.txt'], HOST, _session_ok(), _cfg(), None, USER)
        assert any('not found' in l.lower() or '✗' in l for l in lines)


# ── mv ────────────────────────────────────────────────────────────────────────

class TestShellMv:
    def test_mv_not_enough_args(self):
        lines = _dispatch('mv', ['only_one'], HOST, _session_ok(), _cfg(), None, USER)
        assert any('Usage' in l for l in lines)

    def test_mv_success(self):
        with patch('cli.api.actions.get_csrf', return_value='c'), \
             patch('cli.api.actions.rename', return_value='new'), \
             patch('cli.config.rename_local_drop'):
            lines = _dispatch('mv', ['old', 'new'], HOST, _session_ok(), _cfg(), None, USER)
        assert any('✓' in l for l in lines)


# ── save ──────────────────────────────────────────────────────────────────────

class TestShellSave:
    def test_save_no_args(self):
        lines = _dispatch('save', [], HOST, _session_ok(), _cfg(), None, USER)
        assert any('Usage' in l for l in lines)

    def test_save_success(self):
        with patch('cli.api.actions.get_csrf', return_value='c'), \
             patch('cli.api.actions.save_bookmark', return_value=True):
            lines = _dispatch('save', ['k'], HOST, _session_ok(), _cfg(), None, USER)
        assert any('Bookmarked' in l for l in lines)


# ── renew ─────────────────────────────────────────────────────────────────────

class TestShellRenew:
    def test_renew_no_args(self):
        lines = _dispatch('renew', [], HOST, _session_ok(), _cfg(), None, USER)
        assert any('Usage' in l for l in lines)

    def test_renew_success(self):
        with patch('cli.api.actions.get_csrf', return_value='c'), \
             patch('cli.api.actions.renew', return_value=('2025-12-31', 1)):
            lines = _dispatch('renew', ['k'], HOST, _session_ok(), _cfg(), None, USER)
        assert any('✓' in l for l in lines)

    def test_renew_failure(self):
        with patch('cli.api.actions.get_csrf', return_value='c'), \
             patch('cli.api.actions.renew', return_value=(None, None)):
            lines = _dispatch('renew', ['k'], HOST, _session_ok(), _cfg(), None, USER)
        assert any('✗' in l for l in lines)


# ── lock ──────────────────────────────────────────────────────────────────────

class TestShellLock:
    def test_lock_no_args(self):
        lines = _dispatch('lock', [], HOST, _session_ok(), _cfg(), None, USER)
        assert any('Usage' in l for l in lines)

    def test_lock_remove(self):
        with patch('cli.api.actions.get_csrf', return_value='c'), \
             patch('cli.api.actions.lock_drop', return_value=True):
            lines = _dispatch('lock', ['k', '--remove'], HOST, _session_ok(), _cfg(), None, USER)
        assert any('removed' in l for l in lines)


# ── mkdir ─────────────────────────────────────────────────────────────────────

class TestShellMkdir:
    def test_mkdir_no_args(self):
        lines = _dispatch('mkdir', [], HOST, _session_ok(), _cfg(), None, USER)
        assert any('Usage' in l for l in lines)

    def test_mkdir_success(self):
        with patch('cli.api.actions.get_csrf', return_value='c'), \
             patch('cli.api.actions.create_folder', return_value={'slug': 'docs'}):
            lines = _dispatch('mkdir', ['docs'], HOST, _session_ok(), _cfg(), None, USER)
        assert any('✓' in l for l in lines)

    def test_mkdir_inside_folder(self):
        session = _session_ok({'id': 5})
        with patch('cli.api.actions.get_csrf', return_value='c'), \
             patch('cli.api.actions.create_folder', return_value={'slug': 'sub'}) as mock_mkdir:
            lines = _dispatch('mkdir', ['sub'], HOST, session, _cfg(), 'docs', USER)
        # Should pass parent_id from resolved folder
        assert any('✓' in l for l in lines)


# ── info ──────────────────────────────────────────────────────────────────────

class TestShellInfo:
    def test_info_no_args(self):
        lines = _dispatch('info', [], HOST, _session_ok(), _cfg(), None, USER)
        assert any('Usage' in l for l in lines)

    def test_info_success(self):
        session = _session_ok({
            'kind': 'file', 'filename': 'report.pdf', 'filesize': 1024,
            'created_at': '2025-01-01', 'expires_at': '2025-06-01',
            'view_count': 5,
        })
        lines = _dispatch('info', ['report'], HOST, session, _cfg(), None, USER)
        assert any('report' in l for l in lines)
        assert any('file' in l for l in lines)
        assert any('report.pdf' in l for l in lines)
        assert any('1024' in l for l in lines)

    def test_info_404(self):
        lines = _dispatch('info', ['gone'], HOST, _session_err(404), _cfg(), None, USER)
        assert any('✗' in l for l in lines)


# ── rekey ─────────────────────────────────────────────────────────────────────

class TestShellRekey:
    def test_rekey_not_enough_args(self):
        lines = _dispatch('rekey', ['only_one'], HOST, _session_ok(), _cfg(), None, USER)
        assert any('Usage' in l for l in lines)

    def test_rekey_success(self):
        with patch('cli.api.actions.get_csrf', return_value='c'), \
             patch('cli.api.actions.rename', return_value='new'), \
             patch('cli.config.rename_local_drop'):
            lines = _dispatch('rekey', ['old', 'new'], HOST, _session_ok(), _cfg(), None, USER)
        assert any('✓' in l for l in lines)


# ── cat ───────────────────────────────────────────────────────────────────────

class TestShellCat:
    def test_cat_no_args(self):
        lines = _dispatch('cat', [], HOST, _session_ok(), _cfg(), None, USER)
        assert any('Usage' in l for l in lines)

    def test_cat_text_drop(self):
        session = _session_ok({'kind': 'text', 'content': 'hello\nworld'})
        lines = _dispatch('cat', ['k'], HOST, session, _cfg(), None, USER)
        assert 'hello' in lines
        assert 'world' in lines

    def test_cat_file_drop(self):
        session = _session_ok({'kind': 'file'})
        lines = _dispatch('cat', ['k'], HOST, session, _cfg(), None, USER)
        assert any('file drop' in l for l in lines)

    def test_cat_not_found(self):
        lines = _dispatch('cat', ['k'], HOST, _session_err(404), _cfg(), None, USER)
        assert any('✗' in l for l in lines)


# ── open ──────────────────────────────────────────────────────────────────────

class TestShellOpen:
    def test_open_no_args(self):
        lines = _dispatch('open', [], HOST, _session_ok(), _cfg(), None, USER)
        assert any('Usage' in l for l in lines)

    def test_open_prints_url(self):
        lines = _dispatch('open', ['k'], HOST, _session_ok(), _cfg(), None, USER)
        assert any(f'{HOST}/k/' in l for l in lines)


# ── link ──────────────────────────────────────────────────────────────────────

class TestShellLink:
    def test_link_no_args(self):
        lines = _dispatch('link', [], HOST, _session_ok(), _cfg(), None, USER)
        assert any('Usage' in l for l in lines)

    def test_link_global(self):
        lines = _dispatch('link', ['k'], HOST, _session_ok(), _cfg(), None, USER)
        assert any(f'{HOST}/k/' in l for l in lines)

    def test_link_relative(self):
        session = _session_ok({'folder_path': '/@alice/docs/myfile'})
        lines = _dispatch('link', ['k', '--relative'], HOST, session, _cfg(), None, USER)
        assert any('/@alice/docs/myfile' in l for l in lines)


# ── add ───────────────────────────────────────────────────────────────────────

class TestShellAdd:
    def test_add_no_folder(self):
        lines = _dispatch('add', ['k'], HOST, _session_ok(), _cfg(), None, USER)
        assert any('cd into a folder' in l for l in lines)

    def test_add_no_key(self):
        lines = _dispatch('add', [], HOST, _session_ok(), _cfg(), 'docs', USER)
        assert any('Usage' in l for l in lines)


# ── ls ────────────────────────────────────────────────────────────────────────

class TestShellLs:
    def test_ls_delegates_at_root(self):
        with patch('cli.commands.shell._delegate_to_cli') as mock:
            result = _dispatch('ls', [], HOST, _session_ok(), _cfg(), None, USER)
        assert result is None
        mock.assert_called_once()


# ── Unknown command returns sentinel ──────────────────────────────────────────

class TestShellUnknown:
    def test_unknown_returns_not_handled(self):
        result = _dispatch('xyzzy', [], HOST, _session_ok(), _cfg(), None, USER)
        assert result is _NOT_HANDLED
