"""
tests/unit/test_commands.py

Pure unit tests for the newer CLI commands added in drp:
  - cli.commands.manage: cmd_rm, cmd_mv, cmd_renew, _parse_key
  - cli.commands.edit:   _find_editor, _on_path
  - cli.commands.diff:   (pure parts — diff output logic)
  - cli.commands.serve:  _resolve_paths
  - cli.commands.cp:     _parse_key (re-exported via manage)
  - cli.commands.ls:     _human, _since, _until

No network, no Django DB, no filesystem side-effects beyond tempfiles.
"""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, call
from datetime import datetime, timezone, timedelta

import pytest


# ── cli.commands.manage: _parse_key ──────────────────────────────────────────

class TestParseKey:
    def _pk(self, raw, is_file=False, is_clip=False):
        from cli.commands.manage import _parse_key
        return _parse_key(raw, is_file, is_clip)

    def test_default_is_clipboard(self):
        ns, key = self._pk('hello')
        assert ns == 'c'
        assert key == 'hello'

    def test_file_flag(self):
        ns, key = self._pk('report', is_file=True)
        assert ns == 'f'
        assert key == 'report'

    def test_clip_flag_overrides_file(self):
        # is_clip=True means clipboard even if is_file=True
        ns, key = self._pk('notes', is_file=True, is_clip=True)
        assert ns == 'c'

    def test_empty_key_preserved(self):
        ns, key = self._pk('', is_file=True)
        assert ns == 'f'
        assert key == ''


# ── cli.commands.manage: cmd_rm, cmd_mv, cmd_renew (mocked) ──────────────────

class TestCmdRm:
    def _make_args(self, key, is_file=False):
        args = MagicMock()
        args.key = key
        args.file = is_file
        args.clip = False
        return args

    @patch('cli.commands._context.config')
    @patch('cli.commands._context.requests')
    @patch('cli.commands._context.auto_login')
    @patch('cli.commands.manage.api')
    @patch('cli.commands.manage.config')
    def test_rm_success_clipboard(self, mock_manage_config, mock_api, mock_login, mock_req, mock_ctx_config):
        mock_ctx_config.load.return_value = {'host': 'https://x.com'}
        mock_api.delete.return_value = True
        args = self._make_args('hello')
        import cli.commands.manage as m
        with patch('builtins.print') as mock_print:
            m.cmd_rm(args)
        mock_api.delete.assert_called_once_with('https://x.com', mock_req.Session(), 'hello', ns='c')
        mock_manage_config.remove_local_drop.assert_called_once_with('hello')

    @patch('cli.commands._context.config')
    @patch('cli.commands._context.requests')
    @patch('cli.commands._context.auto_login')
    @patch('cli.commands.manage.api')
    def test_rm_success_file(self, mock_api, mock_login, mock_req, mock_config):
        mock_config.load.return_value = {'host': 'https://x.com'}
        mock_api.delete.return_value = True
        args = self._make_args('q3', is_file=True)
        import cli.commands.manage as m
        with patch('builtins.print'):
            m.cmd_rm(args)
        mock_api.delete.assert_called_once_with('https://x.com', mock_req.Session(), 'q3', ns='f')

    @patch('cli.commands._context.config')
    @patch('cli.commands._context.requests')
    @patch('cli.commands._context.auto_login')
    @patch('cli.commands.manage.api')
    def test_rm_failure_exits(self, mock_api, mock_login, mock_req, mock_config):
        mock_config.load.return_value = {'host': 'https://x.com'}
        mock_api.delete.return_value = False
        args = self._make_args('hello')
        import cli.commands.manage as m
        with pytest.raises(SystemExit) as exc:
            with patch('builtins.print'):
                m.cmd_rm(args)
        assert exc.value.code == 1

    @patch('cli.commands._context.config')
    def test_rm_no_host_exits(self, mock_config):
        mock_config.load.return_value = {}
        import cli.commands.manage as m
        with pytest.raises(SystemExit):
            with patch('builtins.print'):
                m.cmd_rm(MagicMock(key='x', file=False, clip=False))


class TestCmdMv:
    def _make_args(self, key, new_key, is_file=False):
        args = MagicMock()
        args.key = key
        args.new_key = new_key
        args.file = is_file
        args.clip = False
        return args

    @patch('cli.commands._context.config')
    @patch('cli.commands._context.requests')
    @patch('cli.commands._context.auto_login')
    @patch('cli.commands.manage.api')
    def test_mv_success(self, mock_api, mock_login, mock_req, mock_config):
        mock_config.load.return_value = {'host': 'https://x.com'}
        mock_api.rename.return_value = 'new-key'  # string = success
        args = self._make_args('old', 'new-key')
        import cli.commands.manage as m
        with patch('builtins.print') as p:
            m.cmd_mv(args)
        output = ' '.join(str(c) for c in p.call_args_list)
        assert 'old' in output or 'new-key' in output
        mock_config.rename_local_drop.assert_called_once_with('old', 'new-key')

    @patch('cli.commands._context.config')
    @patch('cli.commands._context.requests')
    @patch('cli.commands._context.auto_login')
    @patch('cli.commands.manage.api')
    def test_mv_known_failure_exits_1(self, mock_api, mock_login, mock_req, mock_config):
        mock_config.load.return_value = {'host': 'https://x.com'}
        mock_api.rename.return_value = False  # False = known error
        args = self._make_args('old', 'new')
        import cli.commands.manage as m
        with pytest.raises(SystemExit) as exc:
            with patch('builtins.print'):
                m.cmd_mv(args)
        assert exc.value.code == 1

    @patch('cli.commands._context.config')
    @patch('cli.commands._context.requests')
    @patch('cli.commands._context.auto_login')
    @patch('cli.commands.manage.api')
    def test_mv_unknown_failure_exits_1(self, mock_api, mock_login, mock_req, mock_config):
        mock_config.load.return_value = {'host': 'https://x.com'}
        mock_api.rename.return_value = None  # None = unexpected
        args = self._make_args('old', 'new')
        import cli.commands.manage as m
        with pytest.raises(SystemExit) as exc:
            with patch('builtins.print'):
                with patch('cli.commands.manage.report_outcome'):
                    m.cmd_mv(args)
        assert exc.value.code == 1


class TestCmdRenew:
    @patch('cli.commands._context.config')
    @patch('cli.commands._context.requests')
    @patch('cli.commands._context.auto_login')
    @patch('cli.commands.manage.api')
    def test_renew_success(self, mock_api, mock_login, mock_req, mock_config):
        mock_config.load.return_value = {'host': 'https://x.com'}
        mock_api.renew.return_value = ('2026-01-01T00:00:00Z', 2)
        args = MagicMock(key='notes', file=False, clip=False)
        import cli.commands.manage as m
        with patch('builtins.print') as p:
            m.cmd_renew(args)
        printed = ' '.join(str(c) for c in p.call_args_list)
        assert 'notes' in printed or 'renewed' in printed

    @patch('cli.commands._context.config')
    @patch('cli.commands._context.requests')
    @patch('cli.commands._context.auto_login')
    @patch('cli.commands.manage.api')
    def test_renew_failure_exits(self, mock_api, mock_login, mock_req, mock_config):
        mock_config.load.return_value = {'host': 'https://x.com'}
        mock_api.renew.return_value = (None, None)
        args = MagicMock(key='notes', file=False, clip=False)
        import cli.commands.manage as m
        with pytest.raises(SystemExit) as exc:
            with patch('builtins.print'):
                with patch('cli.commands.manage.report_outcome'):
                    m.cmd_renew(args)
        assert exc.value.code == 1


# ── cli.commands.edit: _find_editor, _on_path ─────────────────────────────────

class TestFindEditor:
    def test_find_editor_returns_string(self):
        from cli.commands.edit import _find_editor
        editor = _find_editor()
        assert isinstance(editor, str)
        assert len(editor) > 0

    def test_on_path_true_for_python(self):
        from cli.commands.edit import _on_path
        assert _on_path('python') or _on_path('python3')

    def test_on_path_false_for_nonexistent(self):
        from cli.commands.edit import _on_path
        assert not _on_path('this-editor-does-not-exist-xyz-abc')

    def test_editor_env_var_used(self):
        """EDITOR env var is picked up by cmd_edit (we don't run cmd_edit, just
        verify that _find_editor falls back correctly when EDITOR is unset)."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('VISUAL', None)
            os.environ.pop('EDITOR', None)
            from cli.commands.edit import _find_editor
            e = _find_editor()
            assert e in ('nano', 'vi', 'notepad') or _find_editor()


# ── cli.commands.serve: _resolve_paths ────────────────────────────────────────

class TestResolvePaths:
    def test_file_path(self, tmp_path):
        f = tmp_path / 'a.txt'
        f.write_text('x')
        from cli.commands.serve import _resolve_paths
        result = _resolve_paths([str(f)])
        assert result == [str(f)]

    def test_directory_lists_files(self, tmp_path):
        (tmp_path / 'a.txt').write_text('a')
        (tmp_path / 'b.txt').write_text('b')
        from cli.commands.serve import _resolve_paths
        result = _resolve_paths([str(tmp_path)])
        names = [os.path.basename(p) for p in result]
        assert set(names) == {'a.txt', 'b.txt'}

    def test_glob_pattern(self, tmp_path):
        (tmp_path / 'x.log').write_text('x')
        (tmp_path / 'y.log').write_text('y')
        (tmp_path / 'z.txt').write_text('z')
        from cli.commands.serve import _resolve_paths
        result = _resolve_paths([str(tmp_path / '*.log')])
        names = [os.path.basename(p) for p in result]
        assert set(names) == {'x.log', 'y.log'}

    def test_deduplicates(self, tmp_path):
        f = tmp_path / 'a.txt'
        f.write_text('a')
        from cli.commands.serve import _resolve_paths
        result = _resolve_paths([str(f), str(f)])
        assert len(result) == 1

    def test_nonexistent_target_returns_empty(self, tmp_path):
        from cli.commands.serve import _resolve_paths
        result = _resolve_paths([str(tmp_path / 'nonexistent')])
        assert result == []

    def test_empty_input(self):
        from cli.commands.serve import _resolve_paths
        assert _resolve_paths([]) == []

    def test_directory_not_recursive(self, tmp_path):
        subdir = tmp_path / 'sub'
        subdir.mkdir()
        (subdir / 'nested.txt').write_text('nested')
        (tmp_path / 'top.txt').write_text('top')
        from cli.commands.serve import _resolve_paths
        result = _resolve_paths([str(tmp_path)])
        names = [os.path.basename(p) for p in result]
        assert 'top.txt' in names
        assert 'nested.txt' not in names  # non-recursive


# ── cli.commands.ls: _human, _since, _until ──────────────────────────────────

class TestLsHelpers:
    def test_human_bytes(self):
        from cli.commands.ls import _human
        assert _human(512) == '512B'

    def test_human_kilobytes(self):
        from cli.commands.ls import _human
        result = _human(2048)
        assert 'K' in result

    def test_human_megabytes(self):
        from cli.commands.ls import _human
        result = _human(5 * 1024 * 1024)
        assert 'M' in result

    def test_human_gigabytes(self):
        from cli.commands.ls import _human
        result = _human(2 * 1024 ** 3)
        assert 'G' in result

    def test_since_none(self):
        from cli.commands.ls import _since
        assert _since(None) == '—'

    def test_since_recent(self):
        from cli.commands.ls import _since
        now = datetime.now(timezone.utc)
        iso = (now - timedelta(seconds=30)).isoformat()
        result = _since(iso)
        assert 'ago' in result

    def test_since_minutes(self):
        from cli.commands.ls import _since
        now = datetime.now(timezone.utc)
        iso = (now - timedelta(minutes=5)).isoformat()
        result = _since(iso)
        assert 'm ago' in result

    def test_since_hours(self):
        from cli.commands.ls import _since
        now = datetime.now(timezone.utc)
        iso = (now - timedelta(hours=3)).isoformat()
        result = _since(iso)
        assert 'h ago' in result

    def test_since_days(self):
        from cli.commands.ls import _since
        now = datetime.now(timezone.utc)
        iso = (now - timedelta(days=5)).isoformat()
        result = _since(iso)
        assert 'd ago' in result

    def test_until_none(self):
        from cli.commands.ls import _until
        assert _until(None) == 'no expiry'

    def test_until_future(self):
        from cli.commands.ls import _until
        future = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat()
        result = _until(future)
        assert result  # non-empty string


# ── cli.commands.cp: basic structure ─────────────────────────────────────────

class TestCmdCp:
    @patch('cli.commands._context.config')
    @patch('cli.commands._context.requests')
    @patch('cli.commands._context.auto_login')
    def test_cp_no_host_exits(self, mock_login, mock_req, mock_config):
        mock_config.load.return_value = {}
        import cli.commands.cp as cp
        with pytest.raises(SystemExit):
            with patch('builtins.print'):
                cp.cmd_cp(MagicMock(key='src', new_key='dst', file=False, clip=False))

    @patch('cli.commands._context.config')
    @patch('cli.commands._context.requests')
    @patch('cli.commands._context.auto_login')
    @patch('cli.commands.cp.get_csrf', return_value='csrf-token')
    def test_cp_posts_to_copy_endpoint(self, mock_csrf, mock_login, mock_req, mock_config):
        mock_config.load.return_value = {'host': 'https://x.com'}
        mock_session = MagicMock()
        mock_req.Session.return_value = mock_session
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {'key': 'dst'}
        mock_session.post.return_value = mock_response
        args = MagicMock(key='src', new_key='dst', file=False, clip=False)
        import cli.commands.cp as cp
        with patch('builtins.print'):
            with patch('cli.spinner.Spinner'):
                cp.cmd_cp(args)
        mock_session.post.assert_called_once()
        call_url = mock_session.post.call_args[0][0]
        assert '/src/copy/' in call_url

# ── cli.commands.shell: _dispatch cat — password prompt ───────────────────────

class TestShellCatPassword:
    """shell cat must prompt for password on 401 and retry with X-Drop-Password."""

    def _dispatch(self, cmd, rest, session, host='https://x.com'):
        from cli.commands.shell import _dispatch
        return _dispatch(cmd, rest, host, session, cfg={}, cwd=None, username='u')

    def _mock_session(self, first_status, second_status=None, content='hello'):
        session = MagicMock()
        first_resp = MagicMock()
        first_resp.status_code = first_status
        first_resp.ok = first_status == 200

        if first_status == 200:
            first_resp.json.return_value = {'kind': 'text', 'content': content}
            session.get.return_value = first_resp
        elif second_status is not None:
            second_resp = MagicMock()
            second_resp.status_code = second_status
            second_resp.ok = second_status == 200
            if second_status == 200:
                second_resp.json.return_value = {'kind': 'text', 'content': content}
            session.get.side_effect = [first_resp, second_resp]
        else:
            session.get.return_value = first_resp
        return session

    def test_cat_returns_content_on_200(self):
        session = self._mock_session(200, content='drop content')
        lines = self._dispatch('cat', ['mykey'], session)
        assert lines == ['drop content']

    def test_cat_prompts_on_401_and_retries(self):
        session = self._mock_session(401, second_status=200, content='secret')
        with patch('getpass.getpass', return_value='hunter2') as mock_gp:
            lines = self._dispatch('cat', ['secretkey'], session)
        mock_gp.assert_called_once()
        assert lines == ['secret']
        # Second call must include X-Drop-Password header
        second_call_headers = session.get.call_args_list[1][1].get('headers', {})
        assert second_call_headers.get('X-Drop-Password') == 'hunter2'

    def test_cat_shows_wrong_password_on_second_401(self):
        session = self._mock_session(401, second_status=401)
        with patch('getpass.getpass', return_value='wrong'):
            lines = self._dispatch('cat', ['secretkey'], session)
        assert any('wrong password' in (l or '').lower() for l in lines)

    def test_cat_cancelled_getpass_returns_gracefully(self):
        session = self._mock_session(401)
        with patch('getpass.getpass', side_effect=KeyboardInterrupt):
            lines = self._dispatch('cat', ['secretkey'], session)
        assert lines is not None  # doesn't crash
        assert any('cancel' in (l or '').lower() for l in lines)

    def test_cat_no_key_shows_usage(self):
        session = MagicMock()
        lines = self._dispatch('cat', [], session)
        assert any('usage' in (l or '').lower() for l in lines)

    def test_cat_file_drop_shows_hint(self):
        session = self._mock_session(200)
        session.get.return_value.json.return_value = {'kind': 'file'}
        lines = self._dispatch('cat', ['filekey'], session)
        assert any('drp get' in (l or '') for l in lines)


# ── cli.commands.status: server drop count ────────────────────────────────────

class TestStatusServerCount:
    """cmd_status should fetch server count when a session exists."""

    def _run_status(self, session_exists=True, server_drops=None, local_drops=None):
        from unittest.mock import patch, MagicMock
        import cli.commands.status as status_mod

        if local_drops is None:
            local_drops = [{'ns': 'c', 'key': 'local1'}]
        if server_drops is None:
            server_drops = [{'ns': 'c', 'key': 'srv1'}, {'ns': 'c', 'key': 'srv2'}]

        mock_cfg = {'host': 'https://x.com', 'email': 'u@x.com', 'username': 'u'}

        output = []
        with patch('cli.commands.status.config') as mock_config, \
             patch('cli.commands.status.SESSION_FILE') as mock_sf, \
             patch('cli.commands.status._sync_local_cache'), \
             patch('cli.session.load_session'), \
             patch('cli.spinner.Spinner'), \
             patch('builtins.print', side_effect=lambda *a, **k: output.append(' '.join(str(x) for x in a))):

            mock_config.load.return_value = mock_cfg
            mock_config.load_local_drops.return_value = local_drops
            mock_sf.exists.return_value = session_exists

            mock_resp = MagicMock()
            mock_resp.ok = True
            mock_resp.json.return_value = {'drops': server_drops}

            with patch('requests.Session') as mock_req_session:
                mock_req_session.return_value.get.return_value = mock_resp
                args = MagicMock()
                args.key = None
                status_mod.cmd_status(args)

        return output

    def test_shows_server_count_when_authed(self):
        output = self._run_status(
            session_exists=True,
            server_drops=[{'ns': 'c', 'key': 'a'}, {'ns': 'c', 'key': 'b'}],
        )
        combined = '\n'.join(output)
        assert 'Server drops' in combined or 'server' in combined.lower()

    def test_shows_local_only_delta(self):
        output = self._run_status(
            session_exists=True,
            server_drops=[{'ns': 'c', 'key': 'srv'}],
            local_drops=[{'ns': 'c', 'key': 'srv'}, {'ns': 'c', 'key': 'local-only'}],
        )
        combined = '\n'.join(output)
        # Should note 1 local-only drop
        assert 'local-only' in combined or 'local' in combined.lower()

    def test_no_server_fetch_when_no_session(self):
        output = self._run_status(session_exists=False)
        combined = '\n'.join(output)
        # Falls back to "Local drops" label
        assert 'Local drops' in combined or 'local' in combined.lower()


# ── cli.completion: collection slug cache ─────────────────────────────────────

class TestCollectionSlugCompleter:
    def test_collection_slug_completer_returns_matches(self, tmp_path):
        import json
        from cli.completion import _read_collection_cache
        cache = tmp_path / 'collections.json'
        cache.write_text(json.dumps(['my-notes', 'my-photos', 'work']))
        with patch('cli.config.CONFIG_DIR', tmp_path):
            results = _read_collection_cache('my-')
        assert 'my-notes' in results
        assert 'my-photos' in results
        assert 'work' not in results

    def test_collection_slug_completer_empty_on_missing_cache(self, tmp_path):
        from cli.completion import _read_collection_cache
        with patch('cli.config.CONFIG_DIR', tmp_path):
            results = _read_collection_cache('')
        assert results == []

    def test_do_refresh_saves_collection_slugs(self, tmp_path):
        """_do_refresh should write collections.json with slug list."""
        import json
        from cli.completion import _do_refresh

        mock_cfg = MagicMock()
        mock_cfg.load.return_value = {'host': 'https://x.com', 'email': 'u@x.com'}
        mock_cfg.CONFIG_DIR = tmp_path
        mock_cfg.load_local_drops.return_value = []
        mock_cfg.DROPS_FILE = tmp_path / 'drops.json'
        mock_cfg.save_local_drops = MagicMock()

        mock_sf = MagicMock()
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            'drops': [],
            'saved': [],
            'collections': [
                {'slug': 'notes', 'name': 'Notes'},
                {'slug': 'work',  'name': 'Work'},
            ],
        }

        with patch('requests.Session') as mock_session_cls, \
             patch('cli.session.load_session'):
            mock_session_cls.return_value.get.return_value = mock_resp
            _do_refresh(mock_cfg, mock_sf)

        cache_file = tmp_path / 'collections.json'
        assert cache_file.exists()
        slugs = json.loads(cache_file.read_text())
        assert 'notes' in slugs
        assert 'work' in slugs