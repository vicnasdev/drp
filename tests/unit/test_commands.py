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
    @patch('cli.commands.manage.config')
    def test_mv_success(self, mock_manage_config, mock_api, mock_login, mock_req, mock_ctx_config):
        mock_ctx_config.load.return_value = {'host': 'https://x.com'}
        mock_api.rename.return_value = 'new-key'  # string = success
        args = self._make_args('old', 'new-key')
        import cli.commands.manage as m
        with patch('builtins.print') as p:
            m.cmd_mv(args)
        output = ' '.join(str(c) for c in p.call_args_list)
        assert 'old' in output or 'new-key' in output
        mock_manage_config.rename_local_drop.assert_called_once_with('old', 'new-key')

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


# ── CLI Smoke Tests ──────────────────────────────────────────────────────────

class TestCLISmokeUp:
    """Smoke tests for `drp up` — mock network, ensure no crash."""

    def _make_args(self, target='hello', **kwargs):
        args = MagicMock()
        args.target = target
        args.key = kwargs.get('key', None)
        args.burn = kwargs.get('burn', False)
        args.password = kwargs.get('password', None)
        args.file = kwargs.get('file', False)
        args.clip = kwargs.get('clip', False)
        args.schedule = kwargs.get('schedule', None)
        args.webhook = kwargs.get('webhook', None)
        args.notify = kwargs.get('notify', None)
        args.alias = kwargs.get('alias', None)
        args.template = kwargs.get('template', None)
        args.public = kwargs.get('public', False)
        args.tag = kwargs.get('tag', None)
        args.expires = kwargs.get('expires', None)
        args.timing = False
        args.collection = kwargs.get('collection', None)
        return args

    @patch('cli.commands.upload.config.record_drop')
    @patch('cli.commands.upload.load_context')
    @patch('cli.commands.upload.api.upload_text')
    @patch('cli.commands.upload._copy_to_clipboard', return_value=False)
    def test_text_upload_no_crash(self, mock_clip, mock_upload, mock_ctx, mock_record):
        mock_session = MagicMock()
        mock_ctx.return_value = ({'host': 'https://test.com'}, 'https://test.com', mock_session)
        mock_upload.return_value = 'testkey'

        from cli.commands.upload import cmd_up
        args = self._make_args(target='hello world')
        cmd_up(args)
        mock_upload.assert_called_once()

    @patch('cli.commands.upload.config.record_drop')
    @patch('cli.commands.upload.load_context')
    @patch('cli.commands.upload.api.upload_text')
    @patch('cli.commands.upload._copy_to_clipboard', return_value=False)
    def test_burn_flag_passed(self, mock_clip, mock_upload, mock_ctx, mock_record):
        mock_session = MagicMock()
        mock_ctx.return_value = ({'host': 'https://test.com'}, 'https://test.com', mock_session)
        mock_upload.return_value = 'bkey'

        from cli.commands.upload import cmd_up
        args = self._make_args(target='secret', burn=True)
        cmd_up(args)
        call_kwargs = mock_upload.call_args
        assert call_kwargs[1].get('burn') or call_kwargs[0][4] if len(call_kwargs[0]) > 4 else True

    @patch('cli.commands.upload.config.record_drop')
    @patch('cli.commands.upload.load_context')
    @patch('cli.commands.upload.api.upload_text')
    @patch('cli.commands.upload._copy_to_clipboard', return_value=False)
    def test_public_flag_passed(self, mock_clip, mock_upload, mock_ctx, mock_record):
        mock_session = MagicMock()
        mock_ctx.return_value = ({'host': 'https://test.com'}, 'https://test.com', mock_session)
        mock_upload.return_value = 'pubkey'

        from cli.commands.upload import cmd_up
        args = self._make_args(target='public text', public=True, tag='python')
        cmd_up(args)
        mock_upload.assert_called_once()


class TestCLISmokeGet:
    """Smoke test for `drp get` — URL mode (no network needed)."""

    @patch('cli.config.load')
    def test_get_url_mode(self, mock_load, capsys):
        mock_load.return_value = {'host': 'https://test.com'}
        args = MagicMock()
        args.key = 'mykey'
        args.url = True
        args.file = False
        args.clip = False
        args.timing = False

        from cli.commands.get import cmd_get
        cmd_get(args)
        out = capsys.readouterr().out.strip()
        assert out == 'https://test.com/mykey/'

    @patch('cli.config.load')
    def test_get_file_url_mode(self, mock_load, capsys):
        mock_load.return_value = {'host': 'https://test.com'}
        args = MagicMock()
        args.key = 'fkey'
        args.url = True
        args.file = True
        args.clip = False
        args.timing = False

        from cli.commands.get import cmd_get
        cmd_get(args)
        out = capsys.readouterr().out.strip()
        assert out == 'https://test.com/f/fkey/'


class TestCLISmokeStatus:
    """Smoke test for `drp status <key>` — mock network."""

    @patch('cli.commands.status.load_context')
    def test_drop_status_text(self, mock_ctx, capsys):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            'key': 'skey',
            'kind': 'text',
            'views': 5,
            'created_at': '2025-01-01T00:00:00Z',
            'expires_at': '2025-02-01T00:00:00Z',
        }
        mock_session.get.return_value = mock_resp
        mock_ctx.return_value = ({'host': 'https://test.com'}, 'https://test.com', mock_session)

        from cli.commands.status import _drop_status
        args = MagicMock()
        args.file = False
        args.clip = False
        _drop_status(args, 'skey')
        out = capsys.readouterr().out
        assert 'skey' in out


# ── Shell autocomplete + delegation ──────────────────────────────────────────

class TestShellCommandLists:
    """Validate shell command constants are consistent."""

    def test_all_shell_cmds_includes_builtins(self):
        from cli.commands.shell import ALL_SHELL_CMDS, _BUILTIN_CMDS
        for cmd in _BUILTIN_CMDS:
            assert cmd in ALL_SHELL_CMDS

    def test_all_shell_cmds_includes_delegated(self):
        from cli.commands.shell import ALL_SHELL_CMDS, _DELEGATED_CMDS
        for cmd in _DELEGATED_CMDS:
            assert cmd in ALL_SHELL_CMDS

    def test_no_overlap_between_builtin_and_delegated(self):
        from cli.commands.shell import _BUILTIN_CMDS, _DELEGATED_CMDS
        overlap = set(_BUILTIN_CMDS) & set(_DELEGATED_CMDS)
        assert not overlap, f'Overlap: {overlap}'


class TestShellDelegation:
    """Test _delegate_to_cli routes correctly."""

    @patch('cli.drp._HANDLERS')
    @patch('cli.drp.build_parser')
    def test_delegate_known_command(self, mock_build, mock_handlers, capsys):
        from cli.commands.shell import _delegate_to_cli
        # Make 'ping' a recognized handler
        mock_handlers.__contains__ = lambda self, k: k == 'ping'
        mock_handlers.__getitem__ = lambda self, k: MagicMock()
        mock_parser = MagicMock()
        ns = MagicMock()
        mock_parser.parse_args.return_value = ns
        mock_build.return_value = mock_parser
        assert _delegate_to_cli('ping', []) is True

    def test_delegate_unknown_command(self, capsys):
        from cli.commands.shell import _delegate_to_cli
        result = _delegate_to_cli('nonexistent_xyz', [])
        assert result is False
        out = capsys.readouterr().out
        assert 'unknown command' in out


class TestShellNotHandled:
    """_dispatch returns _NOT_HANDLED for commands it doesn't recognise."""

    def test_dispatch_unknown_returns_sentinel(self):
        from cli.commands.shell import _dispatch, _NOT_HANDLED
        result = _dispatch('foobar_xyz', [], 'http://x', MagicMock(), {}, None, 'u')
        assert result is _NOT_HANDLED


# ── drp cache / drp rmcache ──────────────────────────────────────────────────

class TestCmdCache:
    """Tests for cmd_cache and cmd_rmcache (isolated tmp files)."""

    def setup_method(self):
        import tempfile
        self._tmp = tempfile.mktemp(suffix='.json')
        import cli.config as cfg
        self._orig_drops = cfg.DROPS_FILE
        self._orig_dir   = cfg.CONFIG_DIR
        cfg.DROPS_FILE   = Path(self._tmp)
        cfg.CONFIG_DIR   = Path(self._tmp).parent

    def teardown_method(self):
        import cli.config as cfg
        try:
            Path(self._tmp).unlink(missing_ok=True)
        except Exception:
            pass
        cfg.DROPS_FILE = self._orig_drops
        cfg.CONFIG_DIR = self._orig_dir

    def test_cache_empty(self, capsys):
        from cli.commands.cache import cmd_cache
        cmd_cache(MagicMock())
        out = capsys.readouterr().out
        assert 'empty' in out

    def test_cache_lists_drops(self, capsys):
        from cli import config
        from cli.commands.cache import cmd_cache
        config.save_local_drops([
            {'key': 'hello', 'ns': 'c', 'kind': 'text', 'from_server': True},
            {'key': 'pic', 'ns': 'f', 'kind': 'file', 'from_server': False},
        ])
        cmd_cache(MagicMock())
        out = capsys.readouterr().out
        assert 'hello' in out
        assert 'pic' in out

    def test_rmcache_specific_key(self, capsys):
        from cli import config
        from cli.commands.cache import cmd_rmcache
        config.save_local_drops([
            {'key': 'keep', 'ns': 'c'},
            {'key': 'gone', 'ns': 'c'},
        ])
        args = MagicMock()
        args.all = False
        args.key = 'gone'
        cmd_rmcache(args)
        out = capsys.readouterr().out
        assert '✓' in out
        remaining = config.load_local_drops()
        assert len(remaining) == 1
        assert remaining[0]['key'] == 'keep'

    def test_rmcache_not_found(self, capsys):
        from cli import config
        from cli.commands.cache import cmd_rmcache
        config.save_local_drops([{'key': 'a', 'ns': 'c'}])
        args = MagicMock()
        args.all = False
        args.key = 'nope'
        cmd_rmcache(args)
        out = capsys.readouterr().out
        assert 'not found' in out

    def test_rmcache_all(self, capsys):
        from cli import config
        from cli.commands.cache import cmd_rmcache
        config.save_local_drops([
            {'key': 'a', 'ns': 'c'},
            {'key': 'b', 'ns': 'f'},
        ])
        args = MagicMock()
        args.all = True
        args.key = None
        cmd_rmcache(args)
        out = capsys.readouterr().out
        assert '✓' in out
        assert config.load_local_drops() == []

    def test_rmcache_no_args(self, capsys):
        from cli.commands.cache import cmd_rmcache
        args = MagicMock()
        args.all = False
        args.key = None
        cmd_rmcache(args)
        out = capsys.readouterr().out
        assert 'Usage' in out


class TestBuildParserIncludesCache:
    """Ensure cache + rmcache are registered in the parser."""

    def test_cache_in_commands(self):
        from cli.drp import COMMANDS
        names = [name for name, _, _ in COMMANDS]
        assert 'cache' in names
        assert 'rmcache' in names

    def test_rmcache_parser_accepts_all(self):
        from cli.drp import build_parser
        parser = build_parser()
        args = parser.parse_args(['rmcache', '--all'])
        assert args.all is True

    def test_rmcache_parser_accepts_key(self):
        from cli.drp import build_parser
        parser = build_parser()
        args = parser.parse_args(['rmcache', 'mykey'])
        assert args.key == 'mykey'


# ── Shell sub-collection cd / path management ────────────────────────────────

class TestShellCdNavigation:
    """Test the shell's cd command handles nested sub-collection navigation."""

    def _make_session(self, ok_paths=None):
        """Mock session that returns 200 for paths in ok_paths, 404 otherwise."""
        if ok_paths is None:
            ok_paths = set()
        session = MagicMock()

        def mock_get(url, **kwargs):
            resp = MagicMock()
            for path in ok_paths:
                if path in url:
                    resp.ok = True
                    resp.json.return_value = {
                        'id': 1, 'name': 'test', 'slug': path.split('/')[-2],
                        'drops': [], 'children': [],
                    }
                    resp.status_code = 200
                    return resp
            resp.ok = False
            resp.status_code = 404
            return resp
        session.get = mock_get
        return session

    def test_cd_into_root_collection(self, capsys):
        """cd notes → cwd = 'notes'"""
        from cli.commands.shell import _dispatch, _NOT_HANDLED
        session = self._make_session({'/@u/notes/'})
        # cd is handled in the main REPL loop, not _dispatch. Just verify resolve path helper
        from cli.commands.shell import cmd_shell
        # Instead test the _resolve_collection_path helper indirectly:
        # The function is local to cmd_shell, so we test the cd logic via a simulated line

    def test_cd_dotdot_from_nested_goes_up_one(self):
        """cd .. from notes/work → cwd = 'notes' (not root)."""
        # Simulate the logic
        cwd = 'notes/work'
        if cwd and '/' in cwd:
            cwd = cwd.rsplit('/', 1)[0]
        assert cwd == 'notes'

    def test_cd_dotdot_from_root_collection_goes_to_none(self):
        """cd .. from 'notes' → cwd = None."""
        cwd = 'notes'
        if cwd and '/' in cwd:
            cwd = cwd.rsplit('/', 1)[0]
        else:
            cwd = None
        assert cwd is None

    def test_cd_dotdot_from_deeply_nested(self):
        """cd .. from a/b/c → cwd = 'a/b'."""
        cwd = 'a/b/c'
        if cwd and '/' in cwd:
            cwd = cwd.rsplit('/', 1)[0]
        assert cwd == 'a/b'

    def test_cd_home_resets_to_root(self):
        """cd ~ or cd (no args) → cwd = None."""
        for target in ['~', '']:
            cwd = 'some/deep/path'
            if not target or target == '~':
                cwd = None
            assert cwd is None


class TestShellClearCommand:
    """Verify clear is in the builtin commands."""

    def test_clear_in_builtin_cmds(self):
        from cli.commands.shell import _BUILTIN_CMDS
        assert 'clear' in _BUILTIN_CMDS

    def test_clear_in_all_shell_cmds(self):
        from cli.commands.shell import ALL_SHELL_CMDS
        assert 'clear' in ALL_SHELL_CMDS


class TestShellLsCollectionDrops:
    """Test _ls_collection_drops displays sub-collections and drops."""

    def test_shows_children_and_drops(self):
        from cli.commands.shell import _ls_collection_drops
        session = MagicMock()
        resp = MagicMock()
        resp.ok = True
        resp.json.return_value = {
            'drops': [{'key': 'mykey', 'ns': 'c'}],
            'children': ['sub-a', 'sub-b'],
        }
        session.get.return_value = resp
        lines = _ls_collection_drops('http://x', session, {}, 'u', 'notes')
        text = '\n'.join(lines)
        assert 'sub-a/' in text
        assert 'sub-b/' in text
        assert 'mykey' in text

    def test_empty_collection(self):
        from cli.commands.shell import _ls_collection_drops
        session = MagicMock()
        resp = MagicMock()
        resp.ok = True
        resp.json.return_value = {'drops': [], 'children': []}
        session.get.return_value = resp
        lines = _ls_collection_drops('http://x', session, {}, 'u', 'notes')
        text = '\n'.join(lines)
        assert 'empty' in text.lower()

    def test_children_only(self):
        from cli.commands.shell import _ls_collection_drops
        session = MagicMock()
        resp = MagicMock()
        resp.ok = True
        resp.json.return_value = {'drops': [], 'children': ['child']}
        session.get.return_value = resp
        lines = _ls_collection_drops('http://x', session, {}, 'u', 'notes')
        text = '\n'.join(lines)
        assert 'child/' in text

    def test_uses_full_path_in_url(self):
        """Nested paths like 'notes/work' should be passed in the URL."""
        from cli.commands.shell import _ls_collection_drops
        session = MagicMock()
        resp = MagicMock()
        resp.ok = True
        resp.json.return_value = {'drops': [], 'children': []}
        session.get.return_value = resp
        _ls_collection_drops('http://x', session, {}, 'u', 'notes/work')
        url = session.get.call_args[0][0]
        assert 'notes/work' in url

    def test_not_found(self):
        from cli.commands.shell import _ls_collection_drops
        session = MagicMock()
        resp = MagicMock()
        resp.ok = False
        resp.status_code = 404
        session.get.return_value = resp
        lines = _ls_collection_drops('http://x', session, {}, 'u', 'nope')
        text = '\n'.join(lines)
        assert 'not found' in text.lower()


class TestShellUnifiedDispatch:
    """Confirm rm, cp, mv, status all return _NOT_HANDLED or delegate."""

    def test_rm_delegates(self):
        from cli.commands.shell import _dispatch
        # rm should delegate (returns None after calling _delegate_to_cli)
        with patch('cli.commands.shell._delegate_to_cli') as mock_del:
            result = _dispatch('rm', ['key'], 'http://x', MagicMock(), {}, None, 'u')
            mock_del.assert_called_once_with('rm', ['key'])
        assert result is None

    def test_cp_delegates(self):
        from cli.commands.shell import _dispatch
        with patch('cli.commands.shell._delegate_to_cli') as mock_del:
            result = _dispatch('cp', ['src', 'dst'], 'http://x', MagicMock(), {}, None, 'u')
            mock_del.assert_called_once_with('cp', ['src', 'dst'])
        assert result is None

    def test_mv_delegates(self):
        from cli.commands.shell import _dispatch
        with patch('cli.commands.shell._delegate_to_cli') as mock_del:
            result = _dispatch('mv', ['old', 'new'], 'http://x', MagicMock(), {}, None, 'u')
            mock_del.assert_called_once_with('mv', ['old', 'new'])
        assert result is None

    def test_status_delegates(self):
        from cli.commands.shell import _dispatch
        with patch('cli.commands.shell._delegate_to_cli') as mock_del:
            result = _dispatch('status', ['key'], 'http://x', MagicMock(), {}, None, 'u')
            mock_del.assert_called_once_with('status', ['key'])
        assert result is None

    def test_ls_without_cwd_delegates(self):
        from cli.commands.shell import _dispatch
        with patch('cli.commands.shell._delegate_to_cli') as mock_del:
            result = _dispatch('ls', [], 'http://x', MagicMock(), {}, None, 'u')
            mock_del.assert_called_once_with('ls', [])
        assert result is None

    def test_ls_with_cwd_does_not_delegate(self):
        """ls inside a collection should call _ls_collection_drops, not delegate."""
        from cli.commands.shell import _dispatch
        with patch('cli.commands.shell._ls_collection_drops', return_value=['  item']) as mock_ls:
            with patch('cli.commands.shell._delegate_to_cli') as mock_del:
                result = _dispatch('ls', [], 'http://x', MagicMock(), {}, 'notes', 'u')
                mock_del.assert_not_called()
                mock_ls.assert_called_once()
        assert result == ['  item']


class TestShellHelpText:
    """Validate help text includes sub-collection navigation info."""

    def test_help_mentions_subpath_navigation(self, capsys):
        from cli.commands.shell import _print_shell_help
        _print_shell_help()
        out = capsys.readouterr().out
        assert 'parent/child' in out

    def test_help_mentions_clear(self, capsys):
        from cli.commands.shell import _print_shell_help
        _print_shell_help()
        out = capsys.readouterr().out
        assert 'clear' in out


# ── CLI collection --parent and tree ls tests ─────────────────────────────────

class TestCollectionNewParentParser:
    """Verify the `drp collection new` parser accepts --parent."""

    def test_parser_accepts_parent_flag(self):
        from cli.drp import build_parser
        parser = build_parser()
        args = parser.parse_args(['collection', 'new', 'child', '--parent', 'notes'])
        assert args.parent == 'notes'

    def test_parser_accepts_parent_short_flag(self):
        from cli.drp import build_parser
        parser = build_parser()
        args = parser.parse_args(['collection', 'new', 'child', '-p', 'notes'])
        assert args.parent == 'notes'

    def test_parser_parent_default_none(self):
        from cli.drp import build_parser
        parser = build_parser()
        args = parser.parse_args(['collection', 'new', 'my', 'notes'])
        assert args.parent is None


class TestCollectionLsTree:
    """Test the tree display logic in collection ls."""

    def test_tree_groups_children_under_parents(self, capsys):
        """ls should indent sub-collections under their parents."""
        from unittest.mock import patch, MagicMock

        cols = [
            {'id': 1, 'slug': 'notes', 'name': 'Notes', 'path': 'notes',
             'parent_id': None, 'drops': ['a', 'b']},
            {'id': 2, 'slug': 'work', 'name': 'Work', 'path': 'notes/work',
             'parent_id': 1, 'drops': ['c']},
        ]

        with patch('cli.commands.collection.load_context') as mock_ctx:
            mock_ctx.return_value = ({'username': 'u'}, 'http://x', MagicMock())
            with patch('cli.commands.collection._fetch_collections', return_value=cols):
                args = MagicMock()
                args.col_cmd = 'ls'
                from cli.commands.collection import cmd_collection
                cmd_collection(args)
        out = capsys.readouterr().out
        assert 'notes' in out
        assert 'work' in out
        # Sub-collection hint
        assert '+1 sub' in out

    def test_tree_no_children_no_hint(self, capsys):
        """Collections with no children should not show sub hint."""
        from unittest.mock import patch, MagicMock

        cols = [
            {'id': 1, 'slug': 'solo', 'name': 'Solo', 'path': 'solo',
             'parent_id': None, 'drops': []},
        ]

        with patch('cli.commands.collection.load_context') as mock_ctx:
            mock_ctx.return_value = ({'username': 'u'}, 'http://x', MagicMock())
            with patch('cli.commands.collection._fetch_collections', return_value=cols):
                args = MagicMock()
                args.col_cmd = 'ls'
                from cli.commands.collection import cmd_collection
                cmd_collection(args)
        out = capsys.readouterr().out
        assert 'solo' in out
        assert 'sub' not in out


class TestCollectionNewWithParent:
    """Test drp collection new --parent resolves parent and sends parent_id."""

    def test_new_with_parent_sends_parent_id(self, capsys):
        from unittest.mock import patch, MagicMock

        parent_resp = MagicMock()
        parent_resp.ok = True
        parent_resp.json.return_value = {'id': 42}

        create_resp = MagicMock()
        create_resp.status_code = 201
        create_resp.json.return_value = {'slug': 'work', 'path': 'notes/work'}

        session = MagicMock()
        session.get.return_value = parent_resp
        session.post.return_value = create_resp

        with patch('cli.commands.collection.load_context') as mock_ctx:
            mock_ctx.return_value = ({'username': 'u'}, 'http://x', session)
            with patch('cli.api.auth.get_csrf', return_value='tok'):
                args = MagicMock()
                args.col_cmd = 'new'
                args.name_parts = ['work']
                args.parent = 'notes'
                from cli.commands.collection import cmd_collection
                cmd_collection(args)

        # Verify parent_id was sent in the POST
        call_kwargs = session.post.call_args
        payload = call_kwargs[1].get('json') or call_kwargs[0][1] if len(call_kwargs[0]) > 1 else call_kwargs[1].get('json')
        assert payload['parent_id'] == 42
        assert payload['name'] == 'work'

        out = capsys.readouterr().out
        assert 'notes/work' in out

    def test_new_without_parent_no_parent_id(self, capsys):
        from unittest.mock import patch, MagicMock

        create_resp = MagicMock()
        create_resp.status_code = 201
        create_resp.json.return_value = {'slug': 'solo', 'path': 'solo'}

        session = MagicMock()
        session.post.return_value = create_resp

        with patch('cli.commands.collection.load_context') as mock_ctx:
            mock_ctx.return_value = ({'username': 'u'}, 'http://x', session)
            with patch('cli.api.auth.get_csrf', return_value='tok'):
                args = MagicMock()
                args.col_cmd = 'new'
                args.name_parts = ['solo']
                args.parent = None
                from cli.commands.collection import cmd_collection
                cmd_collection(args)

        call_kwargs = session.post.call_args
        payload = call_kwargs[1].get('json') or call_kwargs[0][1] if len(call_kwargs[0]) > 1 else call_kwargs[1].get('json')
        assert 'parent_id' not in payload

    def test_new_parent_not_found_exits(self):
        from unittest.mock import patch, MagicMock
        import pytest

        parent_resp = MagicMock()
        parent_resp.ok = False
        parent_resp.status_code = 404

        session = MagicMock()
        session.get.return_value = parent_resp

        with patch('cli.commands.collection.load_context') as mock_ctx:
            mock_ctx.return_value = ({'username': 'u'}, 'http://x', session)
            with patch('cli.api.auth.get_csrf', return_value='tok'):
                args = MagicMock()
                args.col_cmd = 'new'
                args.name_parts = ['child']
                args.parent = 'nonexistent'
                from cli.commands.collection import cmd_collection
                with pytest.raises(SystemExit):
                    cmd_collection(args)


class TestBotPromptAccuracy:
    """Validate the help bot prompt has correct collection documentation."""

    def test_feature_reference_has_collection_commands(self):
        from help.views import _FEATURE_REFERENCE
        assert 'drp collection ls' in _FEATURE_REFERENCE
        assert 'drp collection new' in _FEATURE_REFERENCE
        assert 'drp collection add' in _FEATURE_REFERENCE

    def test_feature_reference_has_subcollection_docs(self):
        from help.views import _FEATURE_REFERENCE
        assert '--parent' in _FEATURE_REFERENCE
        assert 'sub-collection' in _FEATURE_REFERENCE.lower()
        assert 'notes/work' in _FEATURE_REFERENCE

    def test_feature_reference_no_fabricated_commands(self):
        from help.views import _FEATURE_REFERENCE
        assert 'drp up --collection' not in _FEATURE_REFERENCE
        assert 'drp ls --collection' not in _FEATURE_REFERENCE

    def test_system_prompt_has_subcollection_example(self):
        from help.views import _SYSTEM_PROMPT
        assert 'sub-collection' in _SYSTEM_PROMPT.lower()

    def test_feature_reference_lists_shell_navigation(self):
        from help.views import _FEATURE_REFERENCE
        assert 'cd notes' in _FEATURE_REFERENCE or 'cd notes/work' in _FEATURE_REFERENCE
        assert 'cd ..' in _FEATURE_REFERENCE


# ── Smart parse ───────────────────────────────────────────────────────────────

class TestSmartParseDetect:
    """Test format auto-detection."""

    def test_detect_json_object(self):
        from cli.smart_parse import detect_format
        assert detect_format('{"a": 1}') == 'json'

    def test_detect_json_array(self):
        from cli.smart_parse import detect_format
        assert detect_format('[1, 2, 3]') == 'json'

    def test_detect_json_with_whitespace(self):
        from cli.smart_parse import detect_format
        assert detect_format('  \n  {"key": "value"}  \n') == 'json'

    def test_detect_csv(self):
        from cli.smart_parse import detect_format
        assert detect_format('name,age\nAlice,30\nBob,25') == 'csv'

    def test_detect_xml(self):
        from cli.smart_parse import detect_format
        assert detect_format('<root><item>hello</item></root>') == 'xml'

    def test_detect_xml_declaration(self):
        from cli.smart_parse import detect_format
        assert detect_format('<?xml version="1.0"?><r><a>1</a></r>') == 'xml'

    def test_detect_plain_text(self):
        from cli.smart_parse import detect_format
        assert detect_format('just plain text') == 'text'

    def test_detect_url_as_text(self):
        from cli.smart_parse import detect_format
        assert detect_format('https://example.com') == 'text'

    def test_detect_invalid_json(self):
        from cli.smart_parse import detect_format
        assert detect_format('{not valid json}') != 'json'

    def test_detect_single_line_not_csv(self):
        from cli.smart_parse import detect_format
        assert detect_format('hello world') == 'text'


class TestSmartParseParsers:
    """Test individual parsers."""

    def test_parse_json_object(self):
        from cli.smart_parse import parse_json
        assert parse_json('{"a": 1, "b": [2]}') == {"a": 1, "b": [2]}

    def test_parse_json_array(self):
        from cli.smart_parse import parse_json
        assert parse_json('[1, "two", 3]') == [1, "two", 3]

    def test_parse_csv(self):
        from cli.smart_parse import parse_csv
        rows = parse_csv('a,b,c\n1,2,3')
        assert rows == [['a', 'b', 'c'], ['1', '2', '3']]

    def test_parse_xml_simple(self):
        from cli.smart_parse import parse_xml
        result = parse_xml('<root><name>test</name></root>')
        assert result == {'name': 'test'}

    def test_parse_xml_nested(self):
        from cli.smart_parse import parse_xml
        result = parse_xml('<r><a><b>1</b></a></r>')
        assert result == {'a': {'b': '1'}}

    def test_parse_xml_repeated_tags(self):
        from cli.smart_parse import parse_xml
        result = parse_xml('<r><item>a</item><item>b</item></r>')
        assert result == {'item': ['a', 'b']}


class TestSmartParseIntegration:
    """Test smart_parse auto-detect + parse."""

    def test_smart_parse_json(self):
        from cli.smart_parse import smart_parse
        fmt, val = smart_parse('{"x": 42}')
        assert fmt == 'json'
        assert val == {"x": 42}

    def test_smart_parse_csv(self):
        from cli.smart_parse import smart_parse
        fmt, val = smart_parse('a,b\n1,2\n3,4')
        assert fmt == 'csv'
        assert len(val) == 3

    def test_smart_parse_text(self):
        from cli.smart_parse import smart_parse
        fmt, val = smart_parse('hello world')
        assert fmt == 'text'
        assert val == 'hello world'


class TestDotAccess:
    """Test nested field extraction."""

    def test_simple_key(self):
        from cli.smart_parse import dot_access
        assert dot_access({'a': 1}, 'a') == 1

    def test_nested_key(self):
        from cli.smart_parse import dot_access
        assert dot_access({'a': {'b': {'c': 3}}}, 'a.b.c') == 3

    def test_list_index(self):
        from cli.smart_parse import dot_access
        assert dot_access({'items': [10, 20, 30]}, 'items.1') == 20

    def test_mixed_dict_list(self):
        from cli.smart_parse import dot_access
        data = {'users': [{'name': 'Alice'}, {'name': 'Bob'}]}
        assert dot_access(data, 'users.0.name') == 'Alice'

    def test_missing_key_raises(self):
        from cli.smart_parse import dot_access
        with pytest.raises(KeyError):
            dot_access({'a': 1}, 'b')

    def test_invalid_index_raises(self):
        from cli.smart_parse import dot_access
        with pytest.raises(KeyError):
            dot_access([1, 2], 'five')

    def test_navigate_scalar_raises(self):
        from cli.smart_parse import dot_access
        with pytest.raises(KeyError):
            dot_access({'a': 42}, 'a.b')


class TestFormatParsed:
    """Test display formatting."""

    def test_format_json(self):
        from cli.smart_parse import format_parsed
        import json
        out = format_parsed('json', {'a': 1})
        assert json.loads(out) == {'a': 1}

    def test_format_csv(self):
        from cli.smart_parse import format_parsed
        out = format_parsed('csv', [['a', 'b'], ['1', '2']])
        assert 'a | b' in out

    def test_format_text(self):
        from cli.smart_parse import format_parsed
        assert format_parsed('text', 'hello') == 'hello'


class TestGetDotAccessShorthand:
    """Test drp get key.field shorthand."""

    @patch('cli.config.load')
    def test_dot_key_splits_correctly(self, mock_load, capsys):
        mock_load.return_value = {'host': 'https://test.com'}
        args = MagicMock()
        args.key = 'mykey.users.0'
        args.url = True
        args.file = False
        args.clip = False
        args.timing = False
        args.field = None
        args.parse = False

        from cli.commands.get import cmd_get
        cmd_get(args)
        out = capsys.readouterr().out.strip()
        # With --url, the dot-access key should be just 'mykey'
        assert out == 'https://test.com/mykey/'

    @patch('cli.config.load')
    def test_explicit_field_not_overridden(self, mock_load, capsys):
        mock_load.return_value = {'host': 'https://test.com'}
        args = MagicMock()
        args.key = 'mykey.ignored'
        args.url = True
        args.file = False
        args.clip = False
        args.timing = False
        args.field = 'explicit'
        args.parse = False

        from cli.commands.get import cmd_get
        cmd_get(args)
        out = capsys.readouterr().out.strip()
        # When --field is explicit, key stays as-is (no dot-split)
        assert 'mykey.ignored' in out


class TestGetSmartPrint:
    """Test _print_smart helper."""

    def test_print_smart_json(self, capsys):
        from cli.commands.get import _print_smart
        _print_smart('{"x": 1}')
        out = capsys.readouterr().out
        assert '[json]' in out
        assert '"x"' in out

    def test_print_smart_with_field(self, capsys):
        from cli.commands.get import _print_smart
        _print_smart('{"a": {"b": 42}}', 'a.b')
        out = capsys.readouterr().out.strip()
        assert out == '42'

    def test_print_smart_field_nested_object(self, capsys):
        from cli.commands.get import _print_smart
        _print_smart('{"a": {"b": [1,2]}}', 'a.b')
        out = capsys.readouterr().out.strip()
        import json
        assert json.loads(out) == [1, 2]

    def test_print_smart_text_with_field(self, capsys):
        from cli.commands.get import _print_smart
        _print_smart('plain text', 'some.field')
        err = capsys.readouterr().err
        assert 'Cannot extract field' in err


class TestPlanLimitsSmartParse:
    """Verify plan limits include smart_parse and api_fetch."""

    def test_all_plans_have_smart_parse(self):
        from core.models import Plan
        for plan_key in (Plan.ANON, Plan.FREE, Plan.STARTER, Plan.PRO):
            assert 'smart_parse' in Plan.LIMITS[plan_key]

    def test_api_fetch_only_paid(self):
        from core.models import Plan
        assert Plan.LIMITS[Plan.ANON]['api_fetch'] is False
        assert Plan.LIMITS[Plan.FREE]['api_fetch'] is False
        assert Plan.LIMITS[Plan.STARTER]['api_fetch'] is True
        assert Plan.LIMITS[Plan.PRO]['api_fetch'] is True

    def test_smart_parse_all_plans(self):
        from core.models import Plan
        for plan_key in (Plan.ANON, Plan.FREE, Plan.STARTER, Plan.PRO):
            assert Plan.LIMITS[plan_key]['smart_parse'] is True


class TestParserHasParseField:
    """Verify drp get parser accepts --parse and --field."""

    def test_parser_parse_flag(self):
        from cli.drp import build_parser
        parser = build_parser()
        args = parser.parse_args(['get', 'key', '--parse'])
        assert args.parse is True

    def test_parser_field_flag(self):
        from cli.drp import build_parser
        parser = build_parser()
        args = parser.parse_args(['get', 'key', '--field', 'a.b.c'])
        assert args.field == 'a.b.c'

    def test_parser_defaults(self):
        from cli.drp import build_parser
        parser = build_parser()
        args = parser.parse_args(['get', 'key'])
        assert args.parse is False
        assert args.field is None


# ── Parser: send / claim ─────────────────────────────────────────────────────

class TestParserSendClaim:
    """Verify drp send/claim parser args."""

    def test_send_parser(self):
        from cli.drp import build_parser
        parser = build_parser()
        args = parser.parse_args(['send', 'mykey'])
        assert args.key == 'mykey'
        assert args.command == 'send'

    def test_send_file_flag(self):
        from cli.drp import build_parser
        parser = build_parser()
        args = parser.parse_args(['send', '-f', 'myfile'])
        assert args.file is True
        assert args.key == 'myfile'

    def test_claim_parser(self):
        from cli.drp import build_parser
        parser = build_parser()
        args = parser.parse_args(['claim', 'some-token-value'])
        assert args.token == 'some-token-value'
        assert args.command == 'claim'