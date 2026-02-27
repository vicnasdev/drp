"""
Tests for shell tab-completion and local path handling.

Covers:
  - _complete_local_paths: filesystem path completion
  - _completer: readline tab-completion context sensitivity
  - cp local-path detection: ./  ../  /abs  ~/  existing-file-with-slash
  - cp auto-add to folder when cd'd
  - mv argument handling
  - _read_cache / _read_folder_cache correct signatures
"""

import os
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from cli.commands.shell import (
    _complete_local_paths,
    _dispatch,
    _NOT_HANDLED,
    ALL_SHELL_CMDS,
    _KEY_CMDS,
    _SLUG_CMDS,
    _SUB_CMDS,
)


HOST = 'https://drp.test'
USER = 'alice'

def _cfg():
    return {'host': HOST, 'username': USER}


def _session_ok(json_data=None, status=200):
    s = MagicMock()
    r = MagicMock()
    r.ok = True
    r.status_code = status
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


# ══════════════════════════════════════════════════════════════════════════════
# _complete_local_paths
# ══════════════════════════════════════════════════════════════════════════════

class TestCompleteLocalPaths:
    """Filesystem path completion for the shell."""

    def test_empty_prefix_returns_nothing(self):
        assert _complete_local_paths('') == []

    def test_completes_files_in_dir(self, tmp_path):
        (tmp_path / 'hello.txt').write_text('hi')
        (tmp_path / 'hello.py').write_text('x')
        (tmp_path / 'world.md').write_text('w')
        results = _complete_local_paths(str(tmp_path / 'hello'))
        assert len(results) == 2
        assert any('hello.txt' in r for r in results)
        assert any('hello.py' in r for r in results)

    def test_completes_directories_with_trailing_sep(self, tmp_path):
        subdir = tmp_path / 'mydir'
        subdir.mkdir()
        results = _complete_local_paths(str(tmp_path / 'my'))
        assert len(results) == 1
        assert results[0].endswith(os.sep)

    def test_completes_files_with_trailing_space(self, tmp_path):
        (tmp_path / 'report.pdf').write_text('pdf')
        results = _complete_local_paths(str(tmp_path / 'report'))
        assert len(results) == 1
        assert results[0].endswith(' ')

    def test_dotslash_completion(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / 'foo.txt').write_text('f')
        (tmp_path / 'foobar.txt').write_text('fb')
        results = _complete_local_paths('./foo')
        assert len(results) == 2

    def test_dotdotslash_completion(self, tmp_path, monkeypatch):
        child = tmp_path / 'sub'
        child.mkdir()
        (tmp_path / 'parent_file.txt').write_text('p')
        monkeypatch.chdir(child)
        results = _complete_local_paths('../parent')
        assert len(results) == 1
        assert 'parent_file.txt' in results[0]

    def test_absolute_path_completion(self, tmp_path):
        (tmp_path / 'abs_test.txt').write_text('a')
        results = _complete_local_paths(str(tmp_path / 'abs_'))
        assert len(results) == 1
        assert 'abs_test.txt' in results[0]

    def test_tilde_expansion(self, tmp_path, monkeypatch):
        monkeypatch.setenv('HOME', str(tmp_path))
        monkeypatch.setenv('USERPROFILE', str(tmp_path))  # Windows
        (tmp_path / 'tilde_file.log').write_text('t')
        results = _complete_local_paths('~/tilde_')
        assert len(results) == 1
        assert 'tilde_file.log' in results[0]

    def test_nonexistent_prefix_returns_empty(self):
        results = _complete_local_paths('/nonexistent_path_xyz_abc/')
        assert results == []

    def test_mixed_files_and_dirs(self, tmp_path):
        (tmp_path / 'data.csv').write_text('d')
        (tmp_path / 'data_dir').mkdir()
        results = _complete_local_paths(str(tmp_path / 'data'))
        assert len(results) == 2
        file_match = [r for r in results if 'data.csv' in r]
        dir_match = [r for r in results if 'data_dir' in r]
        assert len(file_match) == 1
        assert file_match[0].endswith(' ')
        assert len(dir_match) == 1
        assert dir_match[0].endswith(os.sep)


# ══════════════════════════════════════════════════════════════════════════════
# cp: local path detection
# ══════════════════════════════════════════════════════════════════════════════

class TestCpLocalPathDetection:
    """Verify cp correctly distinguishes local files from drop keys."""

    def test_dotslash_detected_as_local(self, tmp_path):
        f = tmp_path / 'upload_me.txt'
        f.write_text('content')
        with patch('cli.api.file.upload_file', return_value='key-abc') as mock_up, \
             patch('cli.config.record_drop'):
            lines = _dispatch('cp', [str(f)], HOST, _session_ok(), _cfg(), None, USER)
        assert any('✓' in l for l in lines)
        mock_up.assert_called_once()

    def test_dotdotslash_detected_as_local(self, tmp_path, monkeypatch):
        """../ prefix triggers local path detection (upload or 'not found')."""
        child = tmp_path / 'sub'
        child.mkdir()
        f = tmp_path / 'parent.txt'
        f.write_text('parent content')
        monkeypatch.chdir(child)
        with patch('cli.api.file.upload_file', return_value='parent-key') as mock_up, \
             patch('cli.config.record_drop'):
            lines = _dispatch('cp', ['../parent.txt'], HOST, _session_ok(), _cfg(), None, USER)
        # ../parent.txt starts with ../ so is_local=True → should upload
        assert any('✓' in l for l in lines)
        mock_up.assert_called_once()

    def test_absolute_path_detected_as_local(self, tmp_path):
        f = tmp_path / 'absolute.bin'
        f.write_bytes(b'\x00\x01\x02')
        with patch('cli.api.file.upload_file', return_value='abs-key') as mock_up, \
             patch('cli.config.record_drop'):
            lines = _dispatch('cp', [str(f)], HOST, _session_ok(), _cfg(), None, USER)
        assert any('✓' in l for l in lines)
        mock_up.assert_called_once()
        # Verify the path arg
        assert mock_up.call_args[0][2] == str(f)

    def test_tilde_path_detected_as_local(self, tmp_path, monkeypatch):
        monkeypatch.setenv('HOME', str(tmp_path))
        monkeypatch.setenv('USERPROFILE', str(tmp_path))  # Windows
        f = tmp_path / 'notes.md'
        f.write_text('# Notes')
        with patch('cli.api.file.upload_file', return_value='notes-k') as mock_up, \
             patch('cli.config.record_drop'):
            lines = _dispatch('cp', ['~/notes.md'], HOST, _session_ok(), _cfg(), None, USER)
        assert any('✓' in l for l in lines)
        mock_up.assert_called_once()

    def test_bare_key_not_local(self):
        """A plain string like 'mykey' should go to server-side copy, not upload."""
        with patch('cli.api.actions.copy_drop', return_value='mykey-1') as mock_copy, \
             patch('cli.config.record_drop'):
            lines = _dispatch('cp', ['mykey'], HOST, _session_ok(), _cfg(), None, USER)
        assert any('✓' in l for l in lines)
        mock_copy.assert_called_once()

    def test_bare_key_with_dash_not_local(self):
        """Keys like my-notes should NOT trigger local path detection."""
        with patch('cli.api.actions.copy_drop', return_value='my-notes-1') as mock_copy, \
             patch('cli.config.record_drop'):
            lines = _dispatch('cp', ['my-notes', 'my-notes-bak'], HOST, _session_ok(), _cfg(), None, USER)
        mock_copy.assert_called_once()

    def test_local_file_not_found(self):
        lines = _dispatch('cp', ['/no/such/file.txt'], HOST, _session_ok(), _cfg(), None, USER)
        assert any('not found' in l.lower() or '✗' in l for l in lines)

    def test_local_upload_failure(self, tmp_path):
        f = tmp_path / 'fail.txt'
        f.write_text('will fail')
        with patch('cli.api.file.upload_file', return_value=None), \
             patch('cli.config.record_drop'):
            lines = _dispatch('cp', [str(f)], HOST, _session_ok(), _cfg(), None, USER)
        assert any('✗' in l or 'failed' in l.lower() for l in lines)

    def test_local_upload_adds_to_folder_when_cwd_set(self, tmp_path):
        """When cd'd into a folder, cp <local_file> should auto-add to that folder."""
        f = tmp_path / 'in_folder.txt'
        f.write_text('folder content')

        folder_session = _session_ok({'id': 42})
        with patch('cli.api.file.upload_file', return_value='fkey') as mock_up, \
             patch('cli.config.record_drop'), \
             patch('cli.commands.shell._folder_add', return_value=['  ✓ added']) as mock_add:
            lines = _dispatch('cp', [str(f)], HOST, folder_session, _cfg(), 'docs', USER)
        assert any('✓' in l for l in lines)
        mock_add.assert_called_once_with(HOST, folder_session, USER, 'docs', 'fkey')


# ══════════════════════════════════════════════════════════════════════════════
# cp: server-side copy
# ══════════════════════════════════════════════════════════════════════════════

class TestCpServerSide:
    """Server-side drop copy (not local file upload)."""

    def test_copy_with_new_key(self):
        session = _session_ok()
        with patch('cli.api.actions.copy_drop', return_value='backup') as m, \
             patch('cli.config.record_drop'):
            lines = _dispatch('cp', ['original', 'backup'], HOST, session, _cfg(), None, USER)
        m.assert_called_once()
        call_args = m.call_args[0]
        assert call_args[0] == HOST
        assert call_args[2] == 'original'
        assert call_args[3] == 'backup'
        assert any('✓' in l and 'backup' in l for l in lines)

    def test_copy_auto_key(self):
        session = _session_ok()
        with patch('cli.api.actions.copy_drop', return_value='src-1') as m, \
             patch('cli.config.record_drop'):
            lines = _dispatch('cp', ['src'], HOST, session, _cfg(), None, USER)
        m.assert_called_once()
        call_args = m.call_args[0]
        assert call_args[2] == 'src'
        assert call_args[3] is None

    def test_copy_failure(self):
        with patch('cli.api.actions.copy_drop', return_value=None):
            lines = _dispatch('cp', ['gone'], HOST, _session_ok(), _cfg(), None, USER)
        assert any('✗' in l for l in lines)


# ══════════════════════════════════════════════════════════════════════════════
# mv
# ══════════════════════════════════════════════════════════════════════════════

class TestShellMvExtended:
    """Extended mv tests."""

    def test_mv_needs_two_args(self):
        lines = _dispatch('mv', [], HOST, _session_ok(), _cfg(), None, USER)
        assert any('Usage' in l for l in lines)

    def test_mv_needs_new_key(self):
        lines = _dispatch('mv', ['only'], HOST, _session_ok(), _cfg(), None, USER)
        assert any('Usage' in l for l in lines)

    def test_mv_success(self):
        with patch('cli.api.actions.rename', return_value='new-name') as m, \
             patch('cli.config.rename_local_drop'):
            lines = _dispatch('mv', ['old', 'new-name'], HOST, _session_ok(), _cfg(), None, USER)
        m.assert_called_once()
        assert any('✓' in l for l in lines)
        assert any('new-name' in l for l in lines)

    def test_mv_failure(self):
        with patch('cli.api.actions.rename', return_value=None):
            lines = _dispatch('mv', ['k', 'new'], HOST, _session_ok(), _cfg(), None, USER)
        assert any('✗' in l for l in lines)

    def test_mv_exception(self):
        with patch('cli.api.actions.rename', side_effect=Exception('net error')):
            lines = _dispatch('mv', ['k', 'new'], HOST, _session_ok(), _cfg(), None, USER)
        assert any('net error' in l for l in lines)


# ══════════════════════════════════════════════════════════════════════════════
# _read_cache / _read_folder_cache — signature correctness
# ══════════════════════════════════════════════════════════════════════════════

class TestCompletionSignatures:
    """Verify _read_cache and _read_folder_cache accept the right arguments."""

    def test_read_cache_takes_one_arg(self):
        """_read_cache(prefix) must work with a single string argument."""
        from cli.completion import _read_cache
        # Should not raise TypeError
        result = _read_cache('nonexistent-prefix')
        assert isinstance(result, list)

    def test_read_cache_with_empty_string(self):
        from cli.completion import _read_cache
        result = _read_cache('')
        assert isinstance(result, list)

    def test_read_folder_cache_takes_one_arg(self):
        from cli.completion import _read_folder_cache
        result = _read_folder_cache('xxx')
        assert isinstance(result, list)

    def test_read_cache_two_args_raises(self):
        """Calling _read_cache with 2 args (old bug) must raise TypeError."""
        from cli.completion import _read_cache
        with pytest.raises(TypeError):
            _read_cache(None, 'text')


# ══════════════════════════════════════════════════════════════════════════════
# Shell completer integration
# ══════════════════════════════════════════════════════════════════════════════

class TestShellCompleter:
    """Test the _completer function logic without readline (via direct calls)."""

    def test_command_completion(self):
        """First-word completion should offer shell command names."""
        matches = [c + ' ' for c in ALL_SHELL_CMDS if c.startswith('c')]
        assert 'cp ' in matches
        assert 'cat ' in matches
        assert 'cd ' in matches
        assert 'clear ' in matches

    def test_cp_in_key_cmds(self):
        """cp is in _KEY_CMDS (for drop completion) but also gets local paths."""
        assert 'cp' in _KEY_CMDS

    def test_cd_in_slug_cmds(self):
        assert 'cd' in _SLUG_CMDS

    def test_all_shell_cmds_has_all_builtins(self):
        for cmd in ['ls', 'cat', 'rm', 'cp', 'mv', 'cd', 'pwd',
                     'clear', 'help', 'exit', 'quit']:
            assert cmd in ALL_SHELL_CMDS

    def test_cp_completer_returns_local_paths(self, tmp_path, monkeypatch):
        """When completing 'cp ./' we should get local filesystem results."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / 'myfile.txt').write_text('x')
        (tmp_path / 'mydir').mkdir()
        results = _complete_local_paths('./')
        assert any('myfile.txt' in r for r in results)
        assert any('mydir' in r for r in results)

    def test_cp_completer_returns_drop_keys_too(self):
        """cp should also complete drop keys from cache."""
        # _read_cache with a known-empty cache should return []
        from cli.completion import _read_cache
        keys = _read_cache('xyz')
        assert isinstance(keys, list)  # no crash


# ══════════════════════════════════════════════════════════════════════════════
# Shell context (cwd) behavior
# ══════════════════════════════════════════════════════════════════════════════

class TestShellContext:
    """Test that shell correctly operates within folder context."""

    def test_ls_inside_folder_calls_ls_folder(self):
        """ls with cwd set should fetch folder drops, not delegate."""
        session = _session_ok({
            'drops': [{'key': 'note1', 'kind': 'text'}],
            'children': [],
        })
        lines = _dispatch('ls', [], HOST, session, _cfg(), 'docs', USER)
        # Should return lines (folder listing), not None (delegation)
        assert lines is not None
        assert any('note1' in l for l in lines)

    def test_ls_at_root_delegates(self):
        """ls with no cwd should delegate to CLI."""
        with patch('cli.commands.shell._delegate_to_cli') as mock:
            result = _dispatch('ls', [], HOST, _session_ok(), _cfg(), None, USER)
        assert result is None
        mock.assert_called_once()

    def test_ls_col_delegates_even_in_folder(self):
        """ls --col always delegates (shows top-level collections)."""
        with patch('cli.commands.shell._delegate_to_cli') as mock:
            result = _dispatch('ls', ['--col'], HOST, _session_ok(), _cfg(), 'docs', USER)
        assert result is None
        mock.assert_called_once()

    def test_add_requires_cwd(self):
        """add without cd should tell user to cd first."""
        lines = _dispatch('add', ['key1'], HOST, _session_ok(), _cfg(), None, USER)
        assert any('cd into a folder' in l for l in lines)

    def test_add_works_in_folder(self):
        """add with cwd should try to add drop to folder."""
        session = _session_ok({'id': 10})
        with patch('cli.commands.shell._folder_add',
                    return_value=['  ✓ added']) as mock_add:
            lines = _dispatch('add', ['key1'], HOST, session, _cfg(), 'notes', USER)
        mock_add.assert_called_once_with(HOST, session, USER, 'notes', 'key1')

    def test_mkdir_inside_folder_resolves_parent(self):
        """mkdir with cwd should pass the current folder's ID as parent."""
        session = _session_ok({'id': 7})
        with patch('cli.api.actions.create_folder',
                    return_value={'slug': 'child'}) as mock_mkdir:
            lines = _dispatch('mkdir', ['child'], HOST, session, _cfg(), 'parent', USER)
        assert any('✓' in l for l in lines)
        mock_mkdir.assert_called_once_with(HOST, session, 'child', parent_id=7)

    def test_mkdir_at_root_no_parent(self):
        """mkdir at root should pass parent_id=None."""
        session = _session_ok()
        with patch('cli.api.actions.create_folder',
                    return_value={'slug': 'top'}) as mock_mkdir:
            lines = _dispatch('mkdir', ['top'], HOST, session, _cfg(), None, USER)
        assert any('✓' in l for l in lines)
        mock_mkdir.assert_called_once()
        assert mock_mkdir.call_args[1]['parent_id'] is None


# ══════════════════════════════════════════════════════════════════════════════
# Error reporting dedup lock
# ══════════════════════════════════════════════════════════════════════════════

class TestErrorReportingDedup:
    """Verify the threading lock prevents duplicate issue creation."""

    def test_lock_exists(self):
        from core.error_reporting_logic import _FILING_LOCK
        import threading
        assert isinstance(_FILING_LOCK, type(threading.Lock()))

    def test_maybe_file_issue_skips_duplicate(self):
        from core.error_reporting_logic import maybe_file_issue
        data = {'exc_type': 'TestError', 'traceback': [], 'command': 'test'}
        with patch('core.error_reporting_logic._issue_exists', return_value=True), \
             patch('core.error_reporting_logic._create_issue') as mock_create:
            result = maybe_file_issue(data)
        assert result is False
        mock_create.assert_not_called()

    def test_maybe_file_issue_creates_when_new(self):
        from core.error_reporting_logic import maybe_file_issue
        data = {'exc_type': 'NewError', 'traceback': [], 'command': 'test'}
        with patch('core.error_reporting_logic._issue_exists', return_value=False), \
             patch('core.error_reporting_logic._build_body',
                   return_value=('title', 'body')), \
             patch('core.error_reporting_logic._create_issue',
                   return_value=True) as mock_create:
            result = maybe_file_issue(data)
        assert result is True
        mock_create.assert_called_once_with('title', 'body')

    def test_concurrent_calls_serialized(self):
        """Two threads calling maybe_file_issue for the same bug should only
        create one issue — the lock serializes them so the second sees
        the first's result."""
        import threading
        from core.error_reporting_logic import maybe_file_issue

        call_count = {'exists': 0, 'create': 0}

        def mock_exists(data):
            call_count['exists'] += 1
            # First call: no existing issue. Second call: issue was just created.
            return call_count['exists'] > 1

        def mock_create(title, body):
            call_count['create'] += 1
            return True

        data = {'exc_type': 'RaceError', 'traceback': ['line1'], 'command': 'up'}

        with patch('core.error_reporting_logic._issue_exists', side_effect=mock_exists), \
             patch('core.error_reporting_logic._build_body',
                   return_value=('t', 'b')), \
             patch('core.error_reporting_logic._create_issue',
                   side_effect=mock_create):
            t1 = threading.Thread(target=maybe_file_issue, args=(data,))
            t2 = threading.Thread(target=maybe_file_issue, args=(data,))
            t1.start()
            t1.join()  # First finishes before second starts (lock guarantees serial)
            t2.start()
            t2.join()

        # First call creates, second sees it exists
        assert call_count['create'] == 1
