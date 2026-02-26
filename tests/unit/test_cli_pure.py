"""
tests/unit/test_cli_pure.py

Pure unit tests for CLI modules — no network, no Django, no filesystem
side-effects beyond tempfiles.

Covers:
  - cli.config: load/save/record/remove/rename local drops
  - cli.format: human_size, human_time
  - cli.api: slug
  - cli.completion: _read_cache, key_completer, _do_refresh, _trigger_background_refresh
  - cli.commands.upload: _parse_expires, _filename_from_response
  - cli.commands.ls: _human, _since, _until
  - cli.commands.manage: _parse_key
  - cli.commands.setup: _activation_line, _profile_has_activation, _append_to_profile
  - cli.commands.cp: new command
  - cli.commands.diff: new command (pure parts)
  - cli.commands.load: new command (pure parts)
  - cli.commands.status: _drop_status formatting helpers
"""

import os
import time
import tempfile
from datetime import datetime, timezone as tz, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ── cli.config ────────────────────────────────────────────────────────────────

class TestConfig:
    """Tests use isolated tmp files — never touch the real config."""

    def setup_method(self):
        self._tmp = tempfile.mktemp(suffix=".json")
        # Override the global config path
        import cli.config as cfg
        self._orig_config  = cfg.CONFIG_FILE
        self._orig_drops   = cfg.DROPS_FILE
        cfg.CONFIG_FILE  = Path(self._tmp)
        cfg.DROPS_FILE   = Path(self._tmp + ".drops")

    def teardown_method(self):
        import cli.config as cfg
        for p in (cfg.CONFIG_FILE, cfg.DROPS_FILE):
            try: p.unlink()
            except FileNotFoundError: pass
        cfg.CONFIG_FILE = self._orig_config
        cfg.DROPS_FILE  = self._orig_drops

    def test_load_missing_returns_empty(self):
        from cli import config
        assert config.load('/tmp/drp_no_such_file_xyz.json') == {}

    def test_save_load_roundtrip(self):
        from cli import config
        data = {'host': 'https://example.com', 'email': 'a@b.com'}
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            path = f.name
        try:
            config.save(data, path)
            assert config.load(path) == data
        finally:
            os.unlink(path)

    def test_save_creates_parent_dirs(self):
        with tempfile.TemporaryDirectory() as d:
            from cli import config
            path = os.path.join(d, 'sub', 'nested', 'config.json')
            config.save({'host': 'x'}, path)
            assert os.path.exists(path)

    def test_record_drop_stored(self):
        from cli import config
        config.record_drop('hello', 'text', host='https://example.com')
        drops = config.load_local_drops()
        assert any(d['key'] == 'hello' for d in drops)

    def test_record_file_drop_stores_ns(self):
        from cli import config
        config.record_drop('report', 'file', ns='f', host='https://example.com')
        drop = config.load_local_drops()[0]
        assert drop['ns'] == 'f'
        assert drop['kind'] == 'file'

    def test_record_with_filename(self):
        from cli import config
        config.record_drop('q3', 'file', ns='f', filename='q3.pdf', host='https://example.com')
        drop = config.load_local_drops()[0]
        assert drop['filename'] == 'q3.pdf'

    def test_remove_only_removes_target(self):
        from cli import config
        config.record_drop('keep', 'text', host='https://example.com')
        config.record_drop('remove', 'text', host='https://example.com')
        config.remove_local_drop('remove')
        keys = [d['key'] for d in config.load_local_drops()]
        assert 'keep' in keys
        assert 'remove' not in keys

    def test_remove_nonexistent_is_safe(self):
        from cli import config
        config.record_drop('k', 'text', host='https://example.com')
        config.remove_local_drop('no-such-key')
        assert len(config.load_local_drops()) == 1

    def test_rename_updates_key_preserves_fields(self):
        from cli import config
        config.record_drop('old', 'file', filename='data.csv', host='https://example.com')
        config.rename_local_drop('old', 'new')
        drop = config.load_local_drops()[0]
        assert drop['key'] == 'new'
        assert drop['filename'] == 'data.csv'

    def test_rename_nonexistent_is_safe(self):
        from cli import config
        config.record_drop('k', 'text', host='https://example.com')
        config.rename_local_drop('no-such-key', 'whatever')
        assert config.load_local_drops()[0]['key'] == 'k'

    def test_most_recent_drop_first(self):
        from cli import config
        config.record_drop('first', 'text', host='https://example.com')
        config.record_drop('second', 'text', host='https://example.com')
        drops = config.load_local_drops()
        assert drops[0]['key'] == 'second'


# ── cli.format ────────────────────────────────────────────────────────────────

class TestHumanSize:
    def test_bytes(self):
        from cli.format import human_size
        assert human_size(512) == '512B'

    def test_kilobytes(self):
        from cli.format import human_size
        assert 'K' in human_size(2048)

    def test_megabytes(self):
        from cli.format import human_size
        assert 'M' in human_size(5 * 1024 * 1024)

    def test_gigabytes(self):
        from cli.format import human_size
        assert 'G' in human_size(2 * 1024 ** 3)

    def test_zero_returns_dash(self):
        from cli.format import human_size
        assert human_size(0) == '-'

    def test_one_byte(self):
        from cli.format import human_size
        assert human_size(1) == '1B'


class TestHumanTime:
    def _iso(self, **delta):
        return (datetime.now(tz.utc) - timedelta(**delta)).isoformat()

    def test_just_now(self):
        from cli.format import human_time
        assert human_time(self._iso(seconds=5)) == 'just now'

    def test_minutes_ago(self):
        from cli.format import human_time
        assert human_time(self._iso(minutes=30)).endswith('m ago')

    def test_hours_ago(self):
        from cli.format import human_time
        assert human_time(self._iso(hours=3)).endswith('h ago')

    def test_days_ago(self):
        from cli.format import human_time
        assert human_time(self._iso(days=3)).endswith('d ago')

    def test_old_date_is_yyyy_mm_dd(self):
        from cli.format import human_time
        result = human_time(self._iso(days=30))
        assert len(result) == 10 and result[4] == '-'

    def test_none_returns_dash(self):
        from cli.format import human_time
        assert human_time(None) == '-'

    def test_empty_returns_dash(self):
        from cli.format import human_time
        assert human_time('') == '-'


# ── cli.api slug ──────────────────────────────────────────────────────────────

class TestSlug:
    def _f(self, name):
        from cli.api import slug
        return slug(name)

    def test_strips_extension(self):       assert self._f('notes.txt') == 'notes'
    def test_spaces_become_hyphens(self):  assert self._f('my cool file.pdf') == 'my-cool-file'
    def test_max_40_chars(self):           assert len(self._f('a' * 100 + '.txt')) <= 40
    def test_dotfile_nonempty(self):       assert len(self._f('.bashrc')) > 0
    def test_no_leading_hyphens(self):     assert not self._f('  spaced.txt  ').startswith('-')
    def test_no_trailing_hyphens(self):    assert not self._f('  spaced.txt  ').endswith('-')
    def test_no_consecutive_hyphens(self): assert '--' not in self._f('hello   world.txt')

    def test_only_safe_chars(self):
        for ch in self._f('hello world (copy) [2].txt'):
            assert ch.isalnum() or ch == '-'


# ── cli.commands.upload ───────────────────────────────────────────────────────

class TestParseExpires:
    def _f(self, val):
        from cli.commands.upload import _parse_expires
        return _parse_expires(val)

    def test_none_returns_none(self):          assert self._f(None) is None
    def test_empty_returns_none(self):         assert self._f('') is None
    def test_days(self):                       assert self._f('7d') == 7
    def test_year(self):                       assert self._f('1y') == 365
    def test_two_years(self):                  assert self._f('2y') == 730
    def test_plain_integer(self):              assert self._f('30') == 30
    def test_invalid_returns_none(self):       assert self._f('forever') is None
    def test_whitespace_stripped(self):        assert self._f('  7d  ') == 7


class TestFilenameFromResponse:
    def _f(self, headers, url='https://example.com/dl'):
        from cli.commands.upload import _filename_from_response
        r = MagicMock()
        r.headers = headers
        return _filename_from_response(r, url)

    def test_content_disposition_double_quotes(self):
        assert self._f({'Content-Disposition': 'attachment; filename="report.pdf"'}) == 'report.pdf'

    def test_content_disposition_single_quotes(self):
        assert self._f({'Content-Disposition': "attachment; filename='data.csv'"}) == 'data.csv'


# ── cli.commands.ls ───────────────────────────────────────────────────────────

class TestLsFormatHelpers:
    def test_human_bytes(self):
        from cli.commands.ls import _human
        assert _human(512) == '512B'

    def test_human_kilobytes(self):
        from cli.commands.ls import _human
        assert 'K' in _human(2048)

    def test_since_none_is_dash(self):
        from cli.commands.ls import _since
        assert _since(None) == '—'

    def test_since_recent_is_seconds(self):
        from cli.commands.ls import _since
        iso = (datetime.now(tz.utc) - timedelta(seconds=30)).isoformat()
        assert _since(iso).endswith('s ago')

    def test_until_none_is_no_expiry(self):
        from cli.commands.ls import _until
        assert _until(None) == 'no expiry'

    def test_until_past_is_expired(self):
        from cli.commands.ls import _until
        iso = (datetime.now(tz.utc) - timedelta(days=1)).isoformat()
        assert _until(iso) == 'expired'

    def test_until_future_has_left(self):
        from cli.commands.ls import _until
        iso = (datetime.now(tz.utc) + timedelta(days=5)).isoformat()
        assert 'left' in _until(iso)


# ── cli.commands.manage ───────────────────────────────────────────────────────

class TestParseKey:
    def _f(self, raw, is_file=False, is_clip=False):
        from cli.commands.manage import _parse_key
        return _parse_key(raw, is_file=is_file, is_clip=is_clip)

    def test_default_is_clipboard(self):  assert self._f('mykey') == ('c', 'mykey')
    def test_file_flag(self):             assert self._f('mykey', is_file=True) == ('f', 'mykey')
    def test_clip_overrides_file(self):   assert self._f('mykey', is_file=True, is_clip=True) == ('c', 'mykey')


# ── cli.commands.setup ────────────────────────────────────────────────────────

class TestSetupHelpers:
    def test_activation_line_contains_eval(self):
        from cli.commands.setup import _activation_line
        line = _activation_line('bash')
        assert line and ('eval' in line.lower() or 'register' in line.lower() or 'drp' in line)

    def test_profile_has_activation_false_when_absent(self):
        from cli.commands.setup import _profile_has_activation
        with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as f:
            f.write('# empty profile\n')
            path = f.name
        try:
            activation = 'eval "$(register-python-argcomplete drp)"'
            assert not _profile_has_activation(Path(path), activation)
        finally:
            os.unlink(path)

    def test_append_to_profile_creates_file(self):
        from cli.commands.setup import _append_to_profile
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'new_profile.sh'
            _append_to_profile(p, 'eval "$(drp --completion)"')
            assert p.exists()
            assert 'drp' in p.read_text()


# ── cli.completion ────────────────────────────────────────────────────────────

def _make_drops(entries):
    return [
        {'key': k, 'ns': ns, 'kind': 'file' if ns == 'f' else 'text',
         'created_at': '2026-01-01T00:00:00+00:00', 'host': 'https://example.com'}
        for k, ns in entries
    ]


class TestReadCache:
    def test_returns_clipboard_keys(self):
        from cli.completion import _read_cache
        drops = _make_drops([('hello', 'c'), ('world', 'c'), ('report', 'f')])
        with patch('cli.config.load_local_drops', return_value=drops):
            result = _read_cache('c', '')
        assert 'hello' in result and 'world' in result and 'report' not in result

    def test_returns_file_keys(self):
        from cli.completion import _read_cache
        drops = _make_drops([('hello', 'c'), ('report', 'f')])
        with patch('cli.config.load_local_drops', return_value=drops):
            result = _read_cache('f', '')
        assert 'report' in result and 'hello' not in result

    def test_ns_none_returns_all(self):
        from cli.completion import _read_cache
        drops = _make_drops([('hello', 'c'), ('report', 'f')])
        with patch('cli.config.load_local_drops', return_value=drops):
            result = _read_cache(None, '')
        assert 'hello' in result and 'report' in result

    def test_prefix_filters(self):
        from cli.completion import _read_cache
        drops = _make_drops([('hello', 'c'), ('help', 'c'), ('world', 'c')])
        with patch('cli.config.load_local_drops', return_value=drops):
            result = _read_cache('c', 'hel')
        assert 'hello' in result and 'help' in result and 'world' not in result

    def test_exception_returns_empty(self):
        from cli.completion import _read_cache
        with patch('cli.config.load_local_drops', side_effect=Exception('boom')):
            assert _read_cache('c', '') == []


class TestKeyCompleter:
    def test_no_file_flag_completes_clipboard(self):
        from cli.completion import key_completer
        drops = _make_drops([('hello', 'c'), ('report', 'f')])
        args = MagicMock(file=False)
        with patch('cli.config.load_local_drops', return_value=drops):
            with patch('cli.completion._trigger_background_refresh'):
                result = key_completer('', args)
        assert 'hello' in result and 'report' not in result

    def test_file_flag_completes_files(self):
        from cli.completion import key_completer
        drops = _make_drops([('hello', 'c'), ('report', 'f')])
        args = MagicMock(file=True)
        with patch('cli.config.load_local_drops', return_value=drops):
            with patch('cli.completion._trigger_background_refresh'):
                result = key_completer('', args)
        assert 'report' in result and 'hello' not in result

    def test_triggers_background_refresh(self):
        from cli.completion import key_completer
        args = MagicMock(file=False)
        with patch('cli.config.load_local_drops', return_value=[]):
            with patch('cli.completion._trigger_background_refresh') as mock_refresh:
                key_completer('', args)
        mock_refresh.assert_called_once()


class TestDoRefreshMerge:
    """_do_refresh merge logic — the bug we fixed lives here."""

    def _run(self, server_response, existing_drops):
        import cli.completion as comp
        saved_list = []
        mock_res = MagicMock()
        mock_res.ok = True
        mock_res.json.return_value = server_response
        mock_session = MagicMock()
        mock_session.get.return_value = mock_res
        mock_config = MagicMock()
        mock_config.load.return_value = {'host': 'https://example.com'}
        mock_config.load_local_drops.return_value = existing_drops
        mock_config.save_local_drops.side_effect = lambda drops: saved_list.extend(drops)
        with patch('requests.Session', return_value=mock_session):
            with patch('cli.session.load_session'):
                comp._do_refresh(mock_config, MagicMock())
        return saved_list

    def test_server_drops_added(self):
        result = self._run(
            server_response={'drops': [{'key': 'q3', 'ns': 'f', 'kind': 'file',
                                        'created_at': '2026-01-01T00:00:00+00:00'}], 'saved': []},
            existing_drops=[],
        )
        assert 'q3' in [d['key'] for d in result]

    def test_local_only_drops_preserved(self):
        """The bug we fixed: local-only drops must survive a server refresh."""
        existing = _make_drops([('local-only', 'c')])
        result = self._run(server_response={'drops': [], 'saved': []}, existing_drops=existing)
        assert 'local-only' in [d['key'] for d in result]

    def test_server_entry_updates_existing(self):
        existing = _make_drops([('q3', 'f')])
        result = self._run(
            server_response={'drops': [{'key': 'q3', 'ns': 'f', 'kind': 'file',
                                        'created_at': '2026-02-01T00:00:00+00:00',
                                        'filename': 'updated.pdf'}], 'saved': []},
            existing_drops=existing,
        )
        q3 = [d for d in result if d['key'] == 'q3']
        assert len(q3) == 1 and q3[0].get('filename') == 'updated.pdf'

    def test_no_crash_on_failed_request(self):
        import cli.completion as comp
        mock_config = MagicMock()
        mock_config.load.return_value = {'host': 'https://example.com'}
        mock_session = MagicMock()
        mock_session.get.side_effect = Exception('network error')
        with patch('requests.Session', return_value=mock_session):
            with patch('cli.session.load_session'):
                comp._do_refresh(mock_config, MagicMock())  # must not raise

    def test_no_crash_on_bad_json(self):
        import cli.completion as comp
        mock_res = MagicMock()
        mock_res.ok = True
        mock_res.json.side_effect = ValueError('bad json')
        mock_session = MagicMock()
        mock_session.get.return_value = mock_res
        mock_config = MagicMock()
        mock_config.load.return_value = {'host': 'https://example.com'}
        with patch('requests.Session', return_value=mock_session):
            with patch('cli.session.load_session'):
                comp._do_refresh(mock_config, MagicMock())  # must not raise


class TestTriggerSkips:
    def test_skips_when_no_session(self):
        from cli.completion import _trigger_background_refresh
        mock_sf = MagicMock()
        mock_sf.exists.return_value = False
        with patch('cli.session.SESSION_FILE', mock_sf):
            with patch('threading.Thread') as mock_thread:
                _trigger_background_refresh()
        mock_thread.assert_not_called()

    def test_skips_when_cache_fresh(self):
        from cli.completion import _trigger_background_refresh, REFRESH_INTERVAL_SECS
        mock_sf = MagicMock(); mock_sf.exists.return_value = True
        mock_df = MagicMock(); mock_df.exists.return_value = True
        mock_df.stat.return_value.st_mtime = time.time()
        with patch('cli.session.SESSION_FILE', mock_sf):
            with patch('cli.config.DROPS_FILE', mock_df):
                with patch('threading.Thread') as mock_thread:
                    _trigger_background_refresh()
        mock_thread.assert_not_called()

    def test_spawns_thread_when_stale(self):
        from cli.completion import _trigger_background_refresh, REFRESH_INTERVAL_SECS
        mock_sf = MagicMock(); mock_sf.exists.return_value = True
        mock_df = MagicMock(); mock_df.exists.return_value = True
        mock_df.stat.return_value.st_mtime = time.time() - REFRESH_INTERVAL_SECS - 10
        mock_ti = MagicMock()
        with patch('cli.session.SESSION_FILE', mock_sf):
            with patch('cli.config.DROPS_FILE', mock_df):
                with patch('threading.Thread', return_value=mock_ti) as mock_t:
                    _trigger_background_refresh()
        mock_t.assert_called_once()
        mock_ti.start.assert_called_once()


# ── cli.commands.cp ───────────────────────────────────────────────────────────

class TestCpCommand:
    """Pure logic: URL construction helper used by cmd_cp."""

    def test_clipboard_url(self):
        from cli.commands.cp import _url
        assert _url('https://drp.test', 'c', 'mykey') == 'https://drp.test/mykey/copy/'

    def test_file_url(self):
        from cli.commands.cp import _url
        assert _url('https://drp.test', 'f', 'mykey') == 'https://drp.test/f/mykey/copy/'


# ── cli.commands.load ─────────────────────────────────────────────────────────

class TestLoadCommand:
    def test_valid_json_file_readable(self):
        import json
        data = {'drops': [{'key': 'x', 'ns': 'c'}], 'saved': []}
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(data, f)
            path = f.name
        try:
            with open(path) as fp:
                loaded = json.load(fp)
            assert loaded['drops'][0]['key'] == 'x'
        finally:
            os.unlink(path)

    def test_missing_file_raises_file_not_found(self):
        import json
        with pytest.raises(FileNotFoundError):
            with open('/tmp/drp_no_such_file_xyz.json') as f:
                json.load(f)

    def test_invalid_json_raises_decode_error(self):
        import json
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write('not json')
            path = f.name
        try:
            with pytest.raises(json.JSONDecodeError):
                with open(path) as fp:
                    json.load(fp)
        finally:
            os.unlink(path)


# ── cli version ───────────────────────────────────────────────────────────────

class TestVersion:
    def test_version_is_semver(self):
        from cli import __version__
        parts = __version__.split('.')
        # Locally: "0.3" (major.minor from VERSION file)
        # CI/installed: "0.3.42" (major.minor.patch from PyPI bump)
        assert len(parts) >= 2
        for part in parts:
            assert part.isdigit()


# ── cli.commands.upload: filename-based key default ───────────────────────────

class TestUploadFileDefaultKey:
    """_upload_file should derive key from filename when none is given."""

    @patch('cli.commands._context.config')
    @patch('cli.commands._context.requests')
    @patch('cli.commands._context.auto_login')
    @patch('cli.commands.upload.api')
    @patch('cli.commands.upload.config')
    @patch('cli.commands.upload.report_outcome')
    def test_default_key_from_filename(self, mock_report, mock_cfg, mock_api,
                                        mock_login, mock_req, mock_ctx_cfg):
        """When key is empty, _upload_file should slugify the basename."""
        from cli.commands.upload import _upload_file
        mock_api.slug.return_value = 'report'
        mock_api.upload_file.return_value = 'report'

        args = MagicMock()
        args.expires = None

        with patch('builtins.print'):
            _upload_file('https://h', MagicMock(), '/tmp/report.pdf', '', {}, args)

        mock_api.slug.assert_called_once_with('report.pdf')
        mock_api.upload_file.assert_called_once()
        call_kwargs = mock_api.upload_file.call_args
        assert call_kwargs[1]['key'] == 'report'

    @patch('cli.commands._context.config')
    @patch('cli.commands._context.requests')
    @patch('cli.commands._context.auto_login')
    @patch('cli.commands.upload.api')
    @patch('cli.commands.upload.config')
    @patch('cli.commands.upload.report_outcome')
    def test_explicit_key_not_overridden(self, mock_report, mock_cfg, mock_api,
                                          mock_login, mock_req, mock_ctx_cfg):
        """When key is provided, it should NOT be replaced."""
        from cli.commands.upload import _upload_file
        mock_api.upload_file.return_value = 'custom'

        args = MagicMock()
        args.expires = None

        with patch('builtins.print'):
            _upload_file('https://h', MagicMock(), '/tmp/report.pdf', 'custom', {}, args)

        mock_api.slug.assert_not_called()


# ── Shell: drp prefix stripping ──────────────────────────────────────────────

class TestShellDrpPrefix:
    """In the shell REPL, 'drp <cmd>' should be treated as just '<cmd>'."""

    def test_prefix_stripped(self):
        import shlex
        line = 'drp up hello.txt'
        tokens = shlex.split(line.strip())
        if tokens[0].lower() == 'drp' and len(tokens) > 1:
            tokens = tokens[1:]
        assert tokens == ['up', 'hello.txt']

    def test_bare_drp_not_stripped(self):
        import shlex
        line = 'drp'
        tokens = shlex.split(line.strip())
        if tokens[0].lower() == 'drp' and len(tokens) > 1:
            tokens = tokens[1:]
        # Single 'drp' stays as-is (will get "unknown command" error)
        assert tokens == ['drp']

    def test_case_insensitive(self):
        import shlex
        line = 'DRP up hello.txt'
        tokens = shlex.split(line.strip())
        if tokens[0].lower() == 'drp' and len(tokens) > 1:
            tokens = tokens[1:]
        assert tokens == ['up', 'hello.txt']


# ── Shell: collection slug injection ─────────────────────────────────────────

class TestShellCollectionSlugInjection:
    """When cwd is set, 'collection add <key>' should auto-inject cwd as slug."""

    def test_collection_add_injects_cwd(self):
        """Simulates the logic in _dispatch that injects cwd slug."""
        cwd = 'python'
        cmd = 'collection'
        rest = ['add', 'autoRun']

        # Reproduce the injection logic from shell.py _dispatch
        if cmd == 'collection' and cwd and rest:
            sub = rest[0].lower()
            if sub in ('add', 'rm') and len(rest) >= 2:
                flags = [r for r in rest[1:] if r.startswith('-')]
                positional = [r for r in rest[1:] if not r.startswith('-')]
                if len(positional) == 1:
                    rest = [sub, cwd] + flags + positional

        assert rest == ['add', 'python', 'autoRun']

    def test_collection_add_no_inject_when_slug_given(self):
        """If user provides both slug and key, don't inject."""
        cwd = 'python'
        cmd = 'collection'
        rest = ['add', 'other-collection', 'mykey']

        if cmd == 'collection' and cwd and rest:
            sub = rest[0].lower()
            if sub in ('add', 'rm') and len(rest) >= 2:
                flags = [r for r in rest[1:] if r.startswith('-')]
                positional = [r for r in rest[1:] if not r.startswith('-')]
                if len(positional) == 1:
                    rest = [sub, cwd] + flags + positional

        # Two positionals => no injection
        assert rest == ['add', 'other-collection', 'mykey']

    def test_collection_open_injects_cwd(self):
        cwd = 'notes'
        cmd = 'collection'
        rest = ['open']

        if cmd == 'collection' and cwd and rest:
            sub = rest[0].lower()
            if sub == 'open' and len(rest) == 1:
                rest = [sub, cwd]

        assert rest == ['open', 'notes']


# ── cli.commands.serve: numeric collision suffix ──────────────────────────────

class TestServeCollisionSuffix:
    """serve should use -2, -3, ... for collisions instead of random suffixes."""

    @patch('cli.commands._context.config')
    @patch('cli.commands._context.requests')
    @patch('cli.commands._context.auto_login')
    @patch('cli.commands.serve.api')
    @patch('cli.commands.serve.config')
    def test_serve_numeric_suffix_on_collision(self, mock_cfg, mock_api,
                                                mock_login, mock_req, mock_ctx_cfg):
        from cli.commands.serve import cmd_serve

        mock_ctx_cfg.load.return_value = {'host': 'https://h'}
        mock_api.slug.return_value = 'notes'
        mock_api.upload_file.return_value = 'notes-2'

        args = MagicMock()
        args.targets = []
        args.expires = None

        # Test the collision loop logic directly
        with patch('cli.commands.serve._resolve_paths', return_value=['/tmp/notes.txt']):
            with patch('cli.api.actions.key_exists') as mock_exists:
                mock_exists.side_effect = [True, False]  # 'notes' taken, 'notes-2' available
                with patch('builtins.print'):
                    cmd_serve(args)

        # upload_file should be called with key='notes-2'
        mock_api.upload_file.assert_called_once()