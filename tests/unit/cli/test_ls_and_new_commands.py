"""
Tests for ls output formatting and the new parser subcommands.
"""

import pytest
from io import StringIO
from unittest.mock import patch, MagicMock
from types import SimpleNamespace

from cli.drp import build_parser, COMMANDS, COMMAND_GROUPS


# ── New parser subcommands ────────────────────────────────────────────────────

class TestNewSubcommands:
    @pytest.fixture(autouse=True)
    def _parser(self):
        self.parser = build_parser()

    def test_rm_key_required(self):
        with pytest.raises(SystemExit):
            self.parser.parse_args(['rm'])

    def test_rm_key_positional(self):
        args = self.parser.parse_args(['rm', 'notes'])
        assert args.key == 'notes'

    def test_mv_requires_two_args(self):
        with pytest.raises(SystemExit):
            self.parser.parse_args(['mv', 'only_one'])

    def test_mv_both_args(self):
        args = self.parser.parse_args(['mv', 'old', 'new'])
        assert args.key == 'old'
        assert args.new_key == 'new'

    def test_cp_key_required(self):
        with pytest.raises(SystemExit):
            self.parser.parse_args(['cp'])

    def test_cp_key_only(self):
        args = self.parser.parse_args(['cp', 'src'])
        assert args.key == 'src'
        assert args.new_key is None

    def test_cp_key_and_dest(self):
        args = self.parser.parse_args(['cp', 'src', 'dst'])
        assert args.key == 'src'
        assert args.new_key == 'dst'

    def test_renew_key_required(self):
        with pytest.raises(SystemExit):
            self.parser.parse_args(['renew'])

    def test_renew_key_positional(self):
        args = self.parser.parse_args(['renew', 'notes'])
        assert args.key == 'notes'

    def test_save_key_required(self):
        with pytest.raises(SystemExit):
            self.parser.parse_args(['save'])

    def test_save_key_positional(self):
        args = self.parser.parse_args(['save', 'notes'])
        assert args.key == 'notes'

    def test_lock_key_required(self):
        with pytest.raises(SystemExit):
            self.parser.parse_args(['lock'])

    def test_lock_set_password(self):
        args = self.parser.parse_args(['lock', 'k', '-p', 'secret'])
        assert args.key == 'k'
        assert args.password == 'secret'

    def test_lock_prompt_mode(self):
        args = self.parser.parse_args(['lock', 'k', '-p'])
        assert args.password == '__prompt__'

    def test_lock_remove(self):
        args = self.parser.parse_args(['lock', 'k', '--remove'])
        assert args.key == 'k'
        assert args.remove is True

    def test_mkdir_name_required(self):
        with pytest.raises(SystemExit):
            self.parser.parse_args(['mkdir'])

    def test_mkdir_name(self):
        args = self.parser.parse_args(['mkdir', 'docs'])
        assert args.name == 'docs'

    def test_mkdir_parent(self):
        args = self.parser.parse_args(['mkdir', 'sub', '--parent', 'docs'])
        assert args.name == 'sub'
        assert args.parent == 'docs'


# ── COMMANDS / COMMAND_GROUPS consistency ─────────────────────────────────────

class TestNewCommandsConsistency:
    def test_rm_in_commands(self):
        names = {n for n, _, _ in COMMANDS}
        assert 'rm' in names

    def test_mv_in_commands(self):
        names = {n for n, _, _ in COMMANDS}
        assert 'mv' in names

    def test_cp_in_commands(self):
        names = {n for n, _, _ in COMMANDS}
        assert 'cp' in names

    def test_renew_in_commands(self):
        names = {n for n, _, _ in COMMANDS}
        assert 'renew' in names

    def test_save_in_commands(self):
        names = {n for n, _, _ in COMMANDS}
        assert 'save' in names

    def test_lock_in_commands(self):
        names = {n for n, _, _ in COMMANDS}
        assert 'lock' in names

    def test_mkdir_in_commands(self):
        names = {n for n, _, _ in COMMANDS}
        assert 'mkdir' in names

    def test_manage_group_exists(self):
        group_names = {g for g, _ in COMMAND_GROUPS}
        assert 'manage' in group_names

    def test_all_new_commands_in_manage_group(self):
        manage_cmds = None
        for label, cmds in COMMAND_GROUPS:
            if label == 'manage':
                manage_cmds = set(cmds)
                break
        assert manage_cmds is not None
        for cmd in ('rm', 'mv', 'cp', 'renew', 'save', 'lock', 'mkdir'):
            assert cmd in manage_cmds, f'{cmd} not in manage group'


# ── ls output formatting ─────────────────────────────────────────────────────

class TestLsOutput:
    """Test that ls shows filename first for file drops."""

    def _run_ls(self, drops, saved=None, folders=None, long_fmt=False):
        """Run cmd_ls with mocked data and capture output."""
        from cli.commands.ls import cmd_ls

        data = {
            'drops': drops,
            'saved': saved or [],
            'folders': folders or [],
        }

        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.status_code = 200
        mock_response.json.return_value = data
        mock_response.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_response

        args = SimpleNamespace(
            col=False, type=None, sort=None, reverse=False,
            export=False, long=long_fmt, bytes=False,
        )
        cfg = {'host': 'https://drp.test', 'username': 'alice'}

        with patch('cli.commands.ls.load_context', return_value=(cfg, 'https://drp.test', mock_session)):
            from io import StringIO
            import sys
            captured = StringIO()
            old_stdout = sys.stdout
            sys.stdout = captured
            try:
                cmd_ls(args)
            finally:
                sys.stdout = old_stdout
        return captured.getvalue()

    def test_short_format_shows_filename_for_file(self):
        drops = [{'key': 'abc123', 'kind': 'file', 'filename': 'report.pdf',
                  'filesize': 1024, 'created_at': '2025-01-01', 'locked': False}]
        out = self._run_ls(drops)
        # Filename should appear before the key
        assert 'report.pdf' in out
        assert 'abc123' in out
        lines = out.strip().split('\n')
        for line in lines:
            if 'report.pdf' in line:
                fn_pos = line.index('report.pdf')
                key_pos = line.index('abc123')
                assert fn_pos < key_pos, 'Filename should appear before key'

    def test_short_format_no_filename_for_text(self):
        drops = [{'key': 'hello', 'kind': 'text', 'filename': '',
                  'filesize': 0, 'created_at': '2025-01-01', 'locked': False}]
        out = self._run_ls(drops)
        assert 'hello' in out

    def test_short_format_no_duplicate_when_same(self):
        """When filename == key, don't show filename separately."""
        drops = [{'key': 'report', 'kind': 'file', 'filename': 'report',
                  'filesize': 1024, 'created_at': '2025-01-01', 'locked': False}]
        out = self._run_ls(drops)
        # Should not show 'report  report' — just one
        lines = [l.strip() for l in out.strip().split('\n') if l.strip()]
        # The line should NOT contain 'report' twice with padding between
        for line in lines:
            parts = line.split()
            # Only one 'report' visible (in the ANSI-colored key)
            assert parts.count('report') <= 1

    def test_long_format_shows_filename(self):
        drops = [{'key': 'q3', 'kind': 'file', 'filename': 'quarterly-report.pdf',
                  'filesize': 2048000, 'created_at': '2025-01-01',
                  'expires_at': '2025-06-01', 'locked': False}]
        out = self._run_ls(drops, long_fmt=True)
        assert 'quarterly-report.pdf' in out
        assert 'q3' in out

    def test_locked_shows_icon(self):
        drops = [{'key': 'k', 'kind': 'text', 'filename': '',
                  'filesize': 0, 'created_at': '2025-01-01', 'locked': True}]
        out = self._run_ls(drops)
        assert '🔒' in out

    def test_empty_drops(self):
        out = self._run_ls([])
        assert 'no drops' in out

    def test_saved_items_show_tag(self):
        out = self._run_ls(
            [],
            saved=[{'key': 'fav', 'saved_at': '2025-01-01'}],
        )
        assert 'fav' in out
        assert 'saved' in out
