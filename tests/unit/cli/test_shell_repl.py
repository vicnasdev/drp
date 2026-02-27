"""
Tests for the drp shell REPL loop and supporting functions.

Exercises the *real* cmd_shell loop by feeding input lines and capturing
output, so we test the full interaction: prompt rendering, cd/cwd mutation,
exit behaviour, pipe filters, folder listing, local file upload with
relative paths, and delegation.

These are the "real tests" — they spin up the actual REPL with mocked I/O
and a mocked session, so every code path is hit exactly as a user would
trigger it.
"""

import os
import pytest
from unittest.mock import patch, MagicMock

from cli.commands.shell import (
    _dispatch,
    _NOT_HANDLED,
    _apply_pipe,
    _complete_local_paths,
    _ls_folder_drops,
    _folder_add,
    _delegate_to_cli,
    cmd_shell,
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


# ── Helpers for REPL tests ────────────────────────────────────────────────────

def _run_shell(input_lines, monkeypatch, capsys, host=HOST, session=None):
    """Run cmd_shell with mocked input/session and return (prompts, stdout)."""
    if session is None:
        session = _session_ok()

    it = iter(input_lines)
    prompts = []

    def mock_input(prompt_str=''):
        prompts.append(prompt_str)
        try:
            return next(it)
        except StopIteration:
            raise EOFError

    monkeypatch.setattr('builtins.input', mock_input)

    with patch('cli.commands.shell.load_context',
               return_value=(_cfg(), host, session)), \
         patch('cli.completion.sync_completions'):
        try:
            cmd_shell(None)
        except SystemExit:
            pass

    return prompts, capsys.readouterr().out


# ══════════════════════════════════════════════════════════════════════════════
# REPL loop — exit/quit/^D
# ══════════════════════════════════════════════════════════════════════════════

class TestReplExit:
    """The shell can be exited in several ways."""

    def test_exit_command(self, monkeypatch, capsys, tmp_path):
        monkeypatch.chdir(tmp_path)
        prompts, _ = _run_shell(['exit'], monkeypatch, capsys)
        assert len(prompts) == 1

    def test_quit_command(self, monkeypatch, capsys, tmp_path):
        monkeypatch.chdir(tmp_path)
        prompts, _ = _run_shell(['quit'], monkeypatch, capsys)
        assert len(prompts) == 1

    def test_q_command(self, monkeypatch, capsys, tmp_path):
        monkeypatch.chdir(tmp_path)
        prompts, _ = _run_shell(['q'], monkeypatch, capsys)
        assert len(prompts) == 1

    def test_eof_exits(self, monkeypatch, capsys, tmp_path):
        """^D (EOF) should exit cleanly."""
        monkeypatch.chdir(tmp_path)
        prompts, _ = _run_shell([], monkeypatch, capsys)
        assert len(prompts) == 1

    def test_cd_dotdot_at_root_exits(self, monkeypatch, capsys, tmp_path):
        """cd .. at root (no folder) should exit like pressing ^D."""
        monkeypatch.chdir(tmp_path)
        prompts, _ = _run_shell(['cd ..'], monkeypatch, capsys)
        assert len(prompts) == 1  # prompted once, then cd .. breaks the loop


# ══════════════════════════════════════════════════════════════════════════════
# REPL loop — prompt rendering
# ══════════════════════════════════════════════════════════════════════════════

class TestReplPrompt:
    """The prompt shows local dir at root and folder path when cd'd."""

    def test_prompt_shows_local_dir(self, monkeypatch, capsys, tmp_path):
        monkeypatch.chdir(tmp_path)
        prompts, _ = _run_shell(['exit'], monkeypatch, capsys)
        # Prompt should contain the temp directory name and 'drp'
        assert 'drp' in prompts[0]

    def test_prompt_shows_folder_after_cd(self, monkeypatch, capsys, tmp_path):
        monkeypatch.chdir(tmp_path)
        session = _session_ok()
        prompts, _ = _run_shell(['cd docs', 'exit'], monkeypatch, capsys, session=session)
        # After cd docs, second prompt should mention docs
        assert len(prompts) >= 2
        assert 'docs' in prompts[1]

    def test_prompt_reverts_after_cd_dotdot(self, monkeypatch, capsys, tmp_path):
        monkeypatch.chdir(tmp_path)
        session = _session_ok()
        prompts, _ = _run_shell(
            ['cd docs', 'cd ..', 'exit'], monkeypatch, capsys, session=session
        )
        assert len(prompts) >= 3
        # First and third prompts are at root (contain 'drp'), second is in folder
        assert 'drp' in prompts[0]
        assert 'docs' in prompts[1]
        assert 'drp' in prompts[2]

    def test_prompt_after_nested_cd(self, monkeypatch, capsys, tmp_path):
        """cd parent, cd child → prompt shows parent/child."""
        monkeypatch.chdir(tmp_path)
        session = _session_ok()
        prompts, _ = _run_shell(
            ['cd parent', 'cd child', 'exit'], monkeypatch, capsys, session=session
        )
        assert len(prompts) >= 3
        assert 'parent/child' in prompts[2]


# ══════════════════════════════════════════════════════════════════════════════
# REPL loop — cd navigation
# ══════════════════════════════════════════════════════════════════════════════

class TestReplCd:
    """cd navigates into folders, cd .. goes up, cd ~ goes to root."""

    def test_cd_into_folder(self, monkeypatch, capsys, tmp_path):
        monkeypatch.chdir(tmp_path)
        session = _session_ok()
        _, out = _run_shell(['cd mydir', 'exit'], monkeypatch, capsys, session=session)
        assert 'mydir' in out  # "now in @alice/mydir"

    def test_cd_dotdot_from_folder(self, monkeypatch, capsys, tmp_path):
        """cd .. from a folder goes to root — does NOT exit the shell."""
        monkeypatch.chdir(tmp_path)
        session = _session_ok()
        prompts, _ = _run_shell(
            ['cd notes', 'cd ..', 'exit'], monkeypatch, capsys, session=session
        )
        # Three prompts: root → notes → root → exit
        assert len(prompts) == 3
        assert 'drp' in prompts[2]  # back at root

    def test_cd_dotdot_nested(self, monkeypatch, capsys, tmp_path):
        """cd .. from nested folder (a/b) goes to parent (a), not root."""
        monkeypatch.chdir(tmp_path)
        session = _session_ok()
        prompts, _ = _run_shell(
            ['cd a', 'cd b', 'cd ..', 'exit'],
            monkeypatch, capsys, session=session,
        )
        # 4 prompts: root → in 'a' → in 'a/b' → back in 'a' → exit
        assert len(prompts) == 4
        # After cd .., prompt shows '@alice/a' (parent), not root
        assert '@' in prompts[3] and 'a' in prompts[3]

    def test_cd_tilde_goes_to_root(self, monkeypatch, capsys, tmp_path):
        monkeypatch.chdir(tmp_path)
        session = _session_ok()
        prompts, _ = _run_shell(
            ['cd deep', 'cd ~', 'exit'], monkeypatch, capsys, session=session
        )
        assert 'drp' in prompts[2]

    def test_cd_no_arg_goes_to_root(self, monkeypatch, capsys, tmp_path):
        monkeypatch.chdir(tmp_path)
        session = _session_ok()
        prompts, _ = _run_shell(
            ['cd stuff', 'cd', 'exit'], monkeypatch, capsys, session=session
        )
        assert 'drp' in prompts[2]

    def test_cd_nonexistent_folder(self, monkeypatch, capsys, tmp_path):
        """cd into a folder that doesn't exist on the server → error."""
        monkeypatch.chdir(tmp_path)
        session = _session_err(404)
        _, out = _run_shell(['cd ghost', 'exit'], monkeypatch, capsys, session=session)
        assert 'not found' in out

    def test_cd_no_username(self, monkeypatch, capsys, tmp_path):
        """cd without a username in config → error."""
        monkeypatch.chdir(tmp_path)
        session = _session_ok()
        cfg_no_user = {'host': HOST, 'username': ''}

        it = iter(['cd docs', 'exit'])
        prompts = []

        def mock_input(prompt_str=''):
            prompts.append(prompt_str)
            try:
                return next(it)
            except StopIteration:
                raise EOFError

        monkeypatch.setattr('builtins.input', mock_input)

        with patch('cli.commands.shell.load_context',
                   return_value=(cfg_no_user, HOST, session)), \
             patch('cli.completion.sync_completions'):
            cmd_shell(None)

        out = capsys.readouterr().out
        assert 'no username' in out.lower() or 'login' in out.lower()


# ══════════════════════════════════════════════════════════════════════════════
# REPL loop — pwd
# ══════════════════════════════════════════════════════════════════════════════

class TestReplPwd:

    def test_pwd_at_root(self, monkeypatch, capsys, tmp_path):
        monkeypatch.chdir(tmp_path)
        _, out = _run_shell(['pwd', 'exit'], monkeypatch, capsys)
        assert 'root' in out

    def test_pwd_in_folder(self, monkeypatch, capsys, tmp_path):
        monkeypatch.chdir(tmp_path)
        session = _session_ok()
        _, out = _run_shell(
            ['cd docs', 'pwd', 'exit'], monkeypatch, capsys, session=session
        )
        assert 'docs' in out


# ══════════════════════════════════════════════════════════════════════════════
# REPL loop — misc commands
# ══════════════════════════════════════════════════════════════════════════════

class TestReplMisc:

    def test_empty_lines_ignored(self, monkeypatch, capsys, tmp_path):
        monkeypatch.chdir(tmp_path)
        prompts, _ = _run_shell(['', '', 'exit'], monkeypatch, capsys)
        assert len(prompts) == 3

    def test_drp_prefix_stripped(self, monkeypatch, capsys, tmp_path):
        monkeypatch.chdir(tmp_path)
        prompts, _ = _run_shell(['drp exit'], monkeypatch, capsys)
        assert len(prompts) == 1

    def test_help_lists_commands(self, monkeypatch, capsys, tmp_path):
        monkeypatch.chdir(tmp_path)
        _, out = _run_shell(['help', 'exit'], monkeypatch, capsys)
        assert 'ls' in out
        assert 'cp' in out
        assert 'rm' in out
        assert 'mkdir' in out

    def test_banner_shows_local_dir(self, monkeypatch, capsys, tmp_path):
        monkeypatch.chdir(tmp_path)
        _, out = _run_shell(['exit'], monkeypatch, capsys)
        # Banner line should mention 'drp'
        assert 'drp' in out


# ══════════════════════════════════════════════════════════════════════════════
# REPL loop — pipe integration
# ══════════════════════════════════════════════════════════════════════════════

class TestReplPipe:
    """Pipe filters applied to dispatch output inside the REPL."""

    def test_cat_pipe_grep(self, monkeypatch, capsys, tmp_path):
        monkeypatch.chdir(tmp_path)
        session = _session_ok({'kind': 'text', 'content': 'apple\nbanana\napricot'})
        _, out = _run_shell(['cat k | grep ap', 'exit'], monkeypatch, capsys, session=session)
        assert 'apple' in out
        assert 'apricot' in out
        assert 'banana' not in out


# ══════════════════════════════════════════════════════════════════════════════
# _apply_pipe — standalone
# ══════════════════════════════════════════════════════════════════════════════

class TestApplyPipe:
    """Inline pipe filters: grep, sort, head, tail."""

    def test_grep_basic(self):
        lines = ['  apple', '  banana', '  apricot', '  cherry']
        result = _apply_pipe(lines, 'grep ap')
        assert result == ['  apple', '  apricot']

    def test_grep_case_insensitive(self):
        lines = ['Hello', 'HELLO', 'world']
        result = _apply_pipe(lines, 'grep hello')
        assert result == ['Hello', 'HELLO']

    def test_grep_regex(self):
        lines = ['key-abc', 'key-123', 'note-xyz']
        result = _apply_pipe(lines, r'grep key-\d+')
        assert result == ['key-123']

    def test_grep_no_match(self):
        result = _apply_pipe(['apple', 'banana'], 'grep zzz')
        assert result == []

    def test_sort(self):
        result = _apply_pipe(['cherry', 'apple', 'banana'], 'sort')
        assert result == ['apple', 'banana', 'cherry']

    def test_head_default_10(self):
        lines = [str(i) for i in range(20)]
        result = _apply_pipe(lines, 'head')
        assert len(result) == 10
        assert result[0] == '0'

    def test_head_custom_n(self):
        result = _apply_pipe(['a', 'b', 'c', 'd', 'e'], 'head 3')
        assert result == ['a', 'b', 'c']

    def test_tail_default_10(self):
        lines = [str(i) for i in range(20)]
        result = _apply_pipe(lines, 'tail')
        assert len(result) == 10
        assert result[0] == '10'

    def test_tail_custom_n(self):
        result = _apply_pipe(['a', 'b', 'c', 'd', 'e'], 'tail 2')
        assert result == ['d', 'e']

    def test_unknown_pipe_passthrough(self):
        lines = ['a', 'b']
        assert _apply_pipe(lines, 'wc -l') == lines

    def test_empty_pipe_expr(self):
        lines = ['a', 'b']
        assert _apply_pipe(lines, '') == lines

    def test_head_on_short_list(self):
        result = _apply_pipe(['one', 'two'], 'head 10')
        assert result == ['one', 'two']

    def test_tail_on_short_list(self):
        result = _apply_pipe(['one', 'two'], 'tail 10')
        assert result == ['one', 'two']

    def test_grep_invalid_regex_falls_back_to_substring(self):
        """Invalid regex should fall back to substring match."""
        lines = ['a[b', 'c[d', 'xyz']
        result = _apply_pipe(lines, 'grep [')
        assert result == ['a[b', 'c[d']


# ══════════════════════════════════════════════════════════════════════════════
# cp — bare filename with real cwd
# ══════════════════════════════════════════════════════════════════════════════

class TestCpBareFilename:
    """cp <filename> should upload when that file exists on disk, and
    server-side copy when it doesn't."""

    def test_bare_filename_exists_uploads(self, tmp_path, monkeypatch):
        """cp file1.txt . → file exists in cwd → upload."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / 'file1.txt').write_text('hello world')
        with patch('cli.api.file.upload_file', return_value='abc-123') as m, \
             patch('cli.config.record_drop'):
            lines = _dispatch('cp', ['file1.txt', '.'], HOST, _session_ok(), _cfg(), None, USER)
        assert any('✓' in l for l in lines)
        assert any('abc-123' in l for l in lines)
        m.assert_called_once()

    def test_bare_filename_not_exists_copies_server(self, tmp_path, monkeypatch):
        """cp somename → no file → server-side copy."""
        monkeypatch.chdir(tmp_path)
        with patch('cli.api.actions.copy_drop', return_value='somename-1') as m, \
             patch('cli.config.record_drop'):
            lines = _dispatch('cp', ['somename'], HOST, _session_ok(), _cfg(), None, USER)
        assert any('✓' in l for l in lines)
        m.assert_called_once()

    def test_bare_csv_exists(self, tmp_path, monkeypatch):
        """cp report.csv . → file exists → upload."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / 'report.csv').write_text('a,b,c')
        with patch('cli.api.file.upload_file', return_value='csv-k') as m, \
             patch('cli.config.record_drop'):
            lines = _dispatch('cp', ['report.csv', '.'], HOST, _session_ok(), _cfg(), None, USER)
        assert any('✓' in l for l in lines)
        m.assert_called_once()

    def test_key_with_dash_no_file(self, tmp_path, monkeypatch):
        """cp my-notes → no file → server-side copy (not upload)."""
        monkeypatch.chdir(tmp_path)
        with patch('cli.api.actions.copy_drop', return_value='my-notes-1') as m, \
             patch('cli.config.record_drop'):
            _dispatch('cp', ['my-notes'], HOST, _session_ok(), _cfg(), None, USER)
        m.assert_called_once()

    def test_bare_json_exists(self, tmp_path, monkeypatch):
        """cp data.json → file exists → upload."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / 'data.json').write_text('{}')
        with patch('cli.api.file.upload_file', return_value='json-k') as m, \
             patch('cli.config.record_drop'):
            lines = _dispatch('cp', ['data.json'], HOST, _session_ok(), _cfg(), None, USER)
        assert any('✓' in l for l in lines)
        m.assert_called_once()


# ══════════════════════════════════════════════════════════════════════════════
# cp — relative paths (./ ../ with cwd changes)
# ══════════════════════════════════════════════════════════════════════════════

class TestCpRelativePaths:
    """cp with ../ and ./ resolved relative to process cwd."""

    def test_dotdot_file_exists_uploads(self, tmp_path, monkeypatch):
        """cp ../parent.txt . → file exists at ../ → upload."""
        child = tmp_path / 'sub'
        child.mkdir()
        (tmp_path / 'parent.txt').write_text('hi from parent')
        monkeypatch.chdir(child)
        with patch('cli.api.file.upload_file', return_value='par-k') as m, \
             patch('cli.config.record_drop'):
            lines = _dispatch('cp', ['../parent.txt', '.'], HOST, _session_ok(), _cfg(), None, USER)
        assert any('✓' in l for l in lines)
        m.assert_called_once()

    def test_dotdot_file_not_exists_errors(self, tmp_path, monkeypatch):
        """cp ../ghost.txt → file doesn't exist → 'not found' error."""
        child = tmp_path / 'sub'
        child.mkdir()
        monkeypatch.chdir(child)
        lines = _dispatch('cp', ['../ghost.txt', '.'], HOST, _session_ok(), _cfg(), None, USER)
        assert any('not found' in l.lower() or '✗' in l for l in lines)

    def test_dotslash_file_exists(self, tmp_path, monkeypatch):
        """cp ./local.txt → upload."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / 'local.txt').write_text('local')
        with patch('cli.api.file.upload_file', return_value='loc-k') as m, \
             patch('cli.config.record_drop'):
            lines = _dispatch('cp', ['./local.txt', '.'], HOST, _session_ok(), _cfg(), None, USER)
        assert any('✓' in l for l in lines)
        m.assert_called_once()

    def test_dotslash_file_not_exists(self, tmp_path, monkeypatch):
        """cp ./nope.txt → not found error."""
        monkeypatch.chdir(tmp_path)
        lines = _dispatch('cp', ['./nope.txt'], HOST, _session_ok(), _cfg(), None, USER)
        assert any('not found' in l.lower() or '✗' in l for l in lines)

    def test_dotdot_nested_two_levels(self, tmp_path, monkeypatch):
        """cp ../../file from two levels deep."""
        grandchild = tmp_path / 'a' / 'b'
        grandchild.mkdir(parents=True)
        (tmp_path / 'deep.txt').write_text('deep content')
        monkeypatch.chdir(grandchild)
        with patch('cli.api.file.upload_file', return_value='deep-k') as m, \
             patch('cli.config.record_drop'):
            lines = _dispatch('cp', ['../../deep.txt', '.'], HOST, _session_ok(), _cfg(), None, USER)
        assert any('✓' in l for l in lines)
        m.assert_called_once()

    def test_absolute_path_upload(self, tmp_path):
        """cp /absolute/path → upload if file exists."""
        f = tmp_path / 'abs.bin'
        f.write_bytes(b'\x00\x01')
        with patch('cli.api.file.upload_file', return_value='abs-k') as m, \
             patch('cli.config.record_drop'):
            lines = _dispatch('cp', [str(f)], HOST, _session_ok(), _cfg(), None, USER)
        assert any('✓' in l for l in lines)
        m.assert_called_once()

    def test_absolute_path_not_exists(self):
        lines = _dispatch('cp', ['/no/such/file.txt'], HOST, _session_ok(), _cfg(), None, USER)
        assert any('not found' in l.lower() or '✗' in l for l in lines)

    def test_tilde_path_upload(self, tmp_path, monkeypatch):
        monkeypatch.setenv('HOME', str(tmp_path))
        monkeypatch.setenv('USERPROFILE', str(tmp_path))
        (tmp_path / 'notes.md').write_text('# hi')
        with patch('cli.api.file.upload_file', return_value='n-k') as m, \
             patch('cli.config.record_drop'):
            lines = _dispatch('cp', ['~/notes.md'], HOST, _session_ok(), _cfg(), None, USER)
        assert any('✓' in l for l in lines)
        m.assert_called_once()


# ══════════════════════════════════════════════════════════════════════════════
# cp — upload via REPL (end-to-end through the loop)
# ══════════════════════════════════════════════════════════════════════════════

class TestCpReplIntegration:
    """Run cp commands through the actual REPL loop."""

    def test_cp_bare_file_in_repl(self, monkeypatch, capsys, tmp_path):
        """Full loop: user types 'cp file1.txt .' and sees upload confirmation."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / 'file1.txt').write_text('data')
        session = _session_ok()
        with patch('cli.api.file.upload_file', return_value='xyz-key'), \
             patch('cli.config.record_drop'):
            _, out = _run_shell(
                ['cp file1.txt .', 'exit'], monkeypatch, capsys, session=session
            )
        assert 'xyz-key' in out
        assert '✓' in out

    def test_cp_dotdot_file_in_repl(self, monkeypatch, capsys, tmp_path):
        """Full loop: cp ../sibling.txt ."""
        child = tmp_path / 'sub'
        child.mkdir()
        (tmp_path / 'sibling.txt').write_text('sibling')
        monkeypatch.chdir(child)
        session = _session_ok()
        with patch('cli.api.file.upload_file', return_value='sib-k'), \
             patch('cli.config.record_drop'):
            _, out = _run_shell(
                ['cp ../sibling.txt .', 'exit'], monkeypatch, capsys, session=session
            )
        assert 'sib-k' in out
        assert '✓' in out

    def test_cp_missing_file_in_repl(self, monkeypatch, capsys, tmp_path):
        """Full loop: cp ../nope.txt . → error shown."""
        child = tmp_path / 'sub'
        child.mkdir()
        monkeypatch.chdir(child)
        _, out = _run_shell(
            ['cp ../nope.txt .', 'exit'], monkeypatch, capsys,
        )
        assert '✗' in out
        assert 'not found' in out.lower()

    def test_cp_server_copy_in_repl(self, monkeypatch, capsys, tmp_path):
        """Full loop: cp mykey newkey → server-side copy."""
        monkeypatch.chdir(tmp_path)
        with patch('cli.api.actions.copy_drop', return_value='newkey'), \
             patch('cli.config.record_drop'):
            _, out = _run_shell(
                ['cp mykey newkey', 'exit'], monkeypatch, capsys,
            )
        assert '✓' in out
        assert 'newkey' in out


# ══════════════════════════════════════════════════════════════════════════════
# _ls_folder_drops
# ══════════════════════════════════════════════════════════════════════════════

class TestLsFolderDrops:
    """Folder listing inside the shell."""

    def test_empty_folder(self):
        session = _session_ok({'drops': [], 'children': []})
        lines = _ls_folder_drops(HOST, session, _cfg(), USER, 'empty')
        assert any('empty folder' in l for l in lines)

    def test_folder_with_text_drops(self):
        drops = [{'key': 'note1', 'kind': 'text'}, {'key': 'note2', 'kind': 'text'}]
        session = _session_ok({'drops': drops, 'children': []})
        lines = _ls_folder_drops(HOST, session, _cfg(), USER, 'docs')
        assert any('note1' in l for l in lines)
        assert any('note2' in l for l in lines)

    def test_folder_with_file_drops(self):
        drops = [{'key': 'img.png', 'kind': 'file'}]
        session = _session_ok({'drops': drops, 'children': []})
        lines = _ls_folder_drops(HOST, session, _cfg(), USER, 'uploads')
        assert any('img.png' in l for l in lines)

    def test_folder_with_children(self):
        session = _session_ok({'drops': [], 'children': ['sub1', 'sub2']})
        lines = _ls_folder_drops(HOST, session, _cfg(), USER, 'parent')
        assert any('sub1' in l for l in lines)
        assert any('sub2' in l for l in lines)

    def test_folder_with_drops_and_children(self):
        session = _session_ok({
            'drops': [{'key': 'k1', 'kind': 'text'}],
            'children': ['child'],
        })
        lines = _ls_folder_drops(HOST, session, _cfg(), USER, 'mixed')
        assert any('child' in l for l in lines)
        assert any('k1' in l for l in lines)

    def test_folder_not_found(self):
        lines = _ls_folder_drops(HOST, _session_err(404), _cfg(), USER, 'gone')
        assert any('✗' in l for l in lines)

    def test_folder_network_error(self):
        session = MagicMock()
        session.get.side_effect = ConnectionError('offline')
        lines = _ls_folder_drops(HOST, session, _cfg(), USER, 'docs')
        assert any('offline' in l for l in lines)

    def test_folder_long_mode(self):
        """ls -l in a folder fetches per-drop metadata."""
        drops = [{'key': 'k1', 'kind': 'text'}]
        # First call returns folder data, second returns drop detail
        folder_resp = MagicMock()
        folder_resp.ok = True
        folder_resp.json.return_value = {'drops': drops, 'children': []}
        detail_resp = MagicMock()
        detail_resp.ok = True
        detail_resp.json.return_value = {
            'kind': 'text', 'filename': '', 'filesize': 0,
            'created_at': '2025-01-01', 'expires_at': '2025-06-01',
            'view_count': 5,
        }
        session = MagicMock()
        session.get.side_effect = [folder_resp, detail_resp]
        lines = _ls_folder_drops(HOST, session, _cfg(), USER, 'docs', long_mode=True)
        assert any('k1' in l for l in lines)

    def test_folder_drops_as_strings(self):
        """Some APIs return drops as plain strings instead of dicts."""
        session = _session_ok({'drops': ['abc', 'def'], 'children': []})
        lines = _ls_folder_drops(HOST, session, _cfg(), USER, 'list')
        # Should handle string drops without crashing
        assert any('abc' in l for l in lines)
        assert any('def' in l for l in lines)


# ══════════════════════════════════════════════════════════════════════════════
# _folder_add
# ══════════════════════════════════════════════════════════════════════════════

class TestFolderAdd:
    """Adding a drop to the current folder."""

    def test_add_success(self):
        session = _session_ok({'id': 42})
        post_resp = MagicMock()
        post_resp.ok = True
        session.post.return_value = post_resp
        with patch('cli.api.auth.get_csrf', return_value='csrf-tok'):
            lines = _folder_add(HOST, session, USER, 'docs', 'mykey')
        assert any('✓' in l for l in lines)
        assert any('mykey' in l for l in lines)

    def test_add_folder_not_found(self):
        lines = _folder_add(HOST, _session_err(404), USER, 'gone', 'k')
        assert any('not found' in l.lower() or '✗' in l for l in lines)

    def test_add_post_failure(self):
        session = _session_ok({'id': 10})
        post_resp = MagicMock()
        post_resp.ok = False
        post_resp.status_code = 400
        post_resp.json.return_value = {'error': 'already in folder'}
        session.post.return_value = post_resp
        with patch('cli.api.auth.get_csrf', return_value='csrf'):
            lines = _folder_add(HOST, session, USER, 'docs', 'k')
        assert any('✗' in l for l in lines)

    def test_add_network_error(self):
        session = MagicMock()
        session.get.side_effect = ConnectionError('offline')
        lines = _folder_add(HOST, session, USER, 'docs', 'k')
        assert any('offline' in l for l in lines)


# ══════════════════════════════════════════════════════════════════════════════
# _delegate_to_cli
# ══════════════════════════════════════════════════════════════════════════════

class TestDelegateToCli:
    """Delegation to top-level CLI parser."""

    def test_unknown_command_prints_error(self, capsys):
        result = _delegate_to_cli('xyzzy', [], host=HOST, session=_session_ok(), username=USER)
        assert result is False
        out = capsys.readouterr().out
        assert 'unknown command' in out

    def test_known_command_is_dispatched(self):
        handler = MagicMock()
        with patch('cli.drp.build_parser') as mock_parser, \
             patch('cli.drp._HANDLERS', {'ping': handler}):
            result = _delegate_to_cli('ping', [], host=HOST, session=_session_ok(), username=USER)
        assert result is True
        handler.assert_called_once()

    def test_handler_exception_caught(self, capsys):
        handler = MagicMock(side_effect=Exception('boom'))
        with patch('cli.drp.build_parser'), \
             patch('cli.drp._HANDLERS', {'ping': handler}):
            result = _delegate_to_cli('ping', [], host=HOST, session=_session_ok(), username=USER)
        assert result is True
        out = capsys.readouterr().out
        assert 'boom' in out

    def test_system_exit_swallowed(self):
        """argparse --help calls sys.exit(0) — we swallow it."""
        handler = MagicMock(side_effect=SystemExit(0))
        with patch('cli.drp.build_parser'), \
             patch('cli.drp._HANDLERS', {'ls': handler}):
            result = _delegate_to_cli('ls', ['--help'], host=HOST, session=_session_ok(), username=USER)
        assert result is True


# ══════════════════════════════════════════════════════════════════════════════
# Local path completion scoping
# ══════════════════════════════════════════════════════════════════════════════

class TestCompletionScoping:
    """_complete_local_paths with various cwd positions."""

    def test_dotslash_lists_cwd(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / 'a.txt').write_text('a')
        (tmp_path / 'adir').mkdir()
        results = _complete_local_paths('./')
        assert len(results) == 2
        assert any('a.txt' in r for r in results)
        assert any('adir' in r for r in results)

    def test_dotdotslash_lists_parent(self, tmp_path, monkeypatch):
        child = tmp_path / 'sub'
        child.mkdir()
        (tmp_path / 'up.txt').write_text('u')
        monkeypatch.chdir(child)
        results = _complete_local_paths('../')
        assert any('up.txt' in r for r in results)

    def test_dir_trailing_sep(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / 'mydir').mkdir()
        results = _complete_local_paths('./my')
        assert len(results) == 1
        assert results[0].endswith(os.sep)

    def test_file_trailing_space(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / 'doc.md').write_text('#')
        results = _complete_local_paths('./doc')
        assert len(results) == 1
        assert results[0].endswith(' ')

    def test_no_match_returns_empty(self):
        results = _complete_local_paths('/nonexistent_xyz_abc_123/')
        assert results == []

    def test_tilde_expands(self, tmp_path, monkeypatch):
        monkeypatch.setenv('HOME', str(tmp_path))
        monkeypatch.setenv('USERPROFILE', str(tmp_path))
        (tmp_path / 'tfoo.txt').write_text('t')
        results = _complete_local_paths('~/tfoo')
        assert len(results) == 1
        assert 'tfoo.txt' in results[0]

    def test_empty_returns_nothing(self):
        assert _complete_local_paths('') == []
