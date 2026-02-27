"""
Tests for cli/completion.py — the simplified completion cache.

Covers:
  - _load_cache / _save_cache: round-trip persistence
  - _read_cache / _read_folder_cache: prefix filtering
  - record_key / remove_key / rename_key / record_folder: cache mutations
  - key_completer / any_key_completer / folder_slug_completer: argcomplete API
  - sync_completions: server fetch → cache write
  - _maybe_background_refresh: staleness gating
"""

import json
import os
import time
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from cli import completion


@pytest.fixture(autouse=True)
def _isolate_cache(tmp_path, monkeypatch):
    """Point COMPLETIONS_FILE at a temp dir so tests don't touch real config."""
    cf = tmp_path / 'completions.json'
    monkeypatch.setattr(completion, 'COMPLETIONS_FILE', cf)
    return cf


# ══════════════════════════════════════════════════════════════════════════════
# _load_cache / _save_cache — round-trip
# ══════════════════════════════════════════════════════════════════════════════

class TestCacheIO:
    def test_load_empty_returns_defaults(self):
        data = completion._load_cache()
        assert data == {'keys': [], 'folders': []}

    def test_round_trip(self, tmp_path):
        data = {'keys': ['a', 'b'], 'folders': ['docs']}
        completion._save_cache(data)
        loaded = completion._load_cache()
        assert loaded == data

    def test_corrupt_json_returns_defaults(self, _isolate_cache):
        _isolate_cache.write_text('NOT JSON!!!')
        data = completion._load_cache()
        assert data == {'keys': [], 'folders': []}

    def test_save_creates_parent_dirs(self, tmp_path, monkeypatch):
        deep = tmp_path / 'a' / 'b' / 'completions.json'
        monkeypatch.setattr(completion, 'COMPLETIONS_FILE', deep)
        completion._save_cache({'keys': ['x'], 'folders': []})
        assert deep.exists()
        assert json.loads(deep.read_text()) == {'keys': ['x'], 'folders': []}

    def test_atomic_write_no_partial(self, tmp_path, _isolate_cache):
        """If _save_cache writes then replaces, there are no .tmp leftovers."""
        completion._save_cache({'keys': ['z'], 'folders': []})
        tmps = list(tmp_path.glob('*.tmp'))
        assert len(tmps) == 0


# ══════════════════════════════════════════════════════════════════════════════
# _read_cache / _read_folder_cache — prefix filtering
# ══════════════════════════════════════════════════════════════════════════════

class TestReadCache:
    def test_empty_cache_returns_empty(self):
        assert completion._read_cache('any') == []
        assert completion._read_folder_cache('any') == []

    def test_prefix_filter_keys(self):
        completion._save_cache({'keys': ['hello', 'help', 'world'], 'folders': []})
        assert completion._read_cache('hel') == ['hello', 'help']
        assert completion._read_cache('w') == ['world']
        assert completion._read_cache('xyz') == []

    def test_empty_prefix_returns_all_keys(self):
        completion._save_cache({'keys': ['a', 'b', 'c'], 'folders': []})
        assert completion._read_cache('') == ['a', 'b', 'c']

    def test_prefix_filter_folders(self):
        completion._save_cache({'keys': [], 'folders': ['docs', 'drafts', 'work']})
        assert completion._read_folder_cache('d') == ['docs', 'drafts']
        assert completion._read_folder_cache('work') == ['work']
        assert completion._read_folder_cache('z') == []

    def test_empty_prefix_returns_all_folders(self):
        completion._save_cache({'keys': [], 'folders': ['x', 'y']})
        assert completion._read_folder_cache('') == ['x', 'y']

    def test_read_cache_takes_one_arg(self):
        """_read_cache(prefix) must work with a single string argument."""
        result = completion._read_cache('nonexistent')
        assert isinstance(result, list)

    def test_read_cache_two_args_raises(self):
        """Old bug: _read_cache(None, 'text') must raise TypeError."""
        with pytest.raises(TypeError):
            completion._read_cache(None, 'text')


# ══════════════════════════════════════════════════════════════════════════════
# record_key / remove_key / rename_key / record_folder
# ══════════════════════════════════════════════════════════════════════════════

class TestCacheMutations:
    def test_record_key_adds(self):
        completion.record_key('hello')
        assert 'hello' in completion._load_cache()['keys']

    def test_record_key_no_duplicates(self):
        completion.record_key('dup')
        completion.record_key('dup')
        keys = completion._load_cache()['keys']
        assert keys.count('dup') == 1

    def test_record_key_prepends(self):
        completion._save_cache({'keys': ['old'], 'folders': []})
        completion.record_key('new')
        assert completion._load_cache()['keys'][0] == 'new'

    def test_remove_key(self):
        completion._save_cache({'keys': ['a', 'b', 'c'], 'folders': []})
        completion.remove_key('b')
        assert completion._load_cache()['keys'] == ['a', 'c']

    def test_remove_key_missing_is_noop(self):
        completion._save_cache({'keys': ['a'], 'folders': []})
        completion.remove_key('zzz')
        assert completion._load_cache()['keys'] == ['a']

    def test_rename_key(self):
        completion._save_cache({'keys': ['old-name', 'other'], 'folders': []})
        completion.rename_key('old-name', 'new-name')
        keys = completion._load_cache()['keys']
        assert 'old-name' not in keys
        assert 'new-name' in keys
        assert 'other' in keys

    def test_rename_key_preserves_position(self):
        completion._save_cache({'keys': ['a', 'target', 'z'], 'folders': []})
        completion.rename_key('target', 'renamed')
        assert completion._load_cache()['keys'] == ['a', 'renamed', 'z']

    def test_record_folder_adds(self):
        completion.record_folder('docs')
        assert 'docs' in completion._load_cache()['folders']

    def test_record_folder_no_duplicates(self):
        completion.record_folder('work')
        completion.record_folder('work')
        folders = completion._load_cache()['folders']
        assert folders.count('work') == 1

    def test_mutations_preserve_other_field(self):
        """record_key should not destroy folders and vice versa."""
        completion._save_cache({'keys': ['k1'], 'folders': ['f1']})
        completion.record_key('k2')
        data = completion._load_cache()
        assert 'k2' in data['keys']
        assert 'f1' in data['folders']

        completion.record_folder('f2')
        data = completion._load_cache()
        assert 'k1' in data['keys']
        assert 'f2' in data['folders']


# ══════════════════════════════════════════════════════════════════════════════
# key_completer / any_key_completer / folder_slug_completer (argcomplete API)
# ══════════════════════════════════════════════════════════════════════════════

class TestArgcompleteAPI:
    def test_key_completer_returns_list(self):
        completion._save_cache({'keys': ['foo', 'foobar'], 'folders': []})
        result = completion.key_completer('foo', MagicMock())
        assert 'foo' in result
        assert 'foobar' in result

    def test_any_key_completer_same_as_key(self):
        completion._save_cache({'keys': ['abc'], 'folders': []})
        result = completion.any_key_completer('a', MagicMock())
        assert result == ['abc']

    def test_folder_slug_completer(self):
        completion._save_cache({'keys': [], 'folders': ['docs', 'drafts']})
        result = completion.folder_slug_completer('d', MagicMock())
        assert 'docs' in result
        assert 'drafts' in result


# ══════════════════════════════════════════════════════════════════════════════
# sync_completions
# ══════════════════════════════════════════════════════════════════════════════

class TestSyncCompletions:
    def _mock_session(self, drops, saved, folders):
        s = MagicMock()
        r = MagicMock()
        r.ok = True
        r.json.return_value = {
            'drops': drops,
            'saved': saved,
            'folders': folders,
        }
        s.get.return_value = r
        return s

    def test_sync_populates_cache(self):
        session = self._mock_session(
            drops=[{'key': 'a'}, {'key': 'b'}],
            saved=[{'key': 'c'}],
            folders=[{'slug': 'docs'}],
        )
        completion.sync_completions(host='https://drp.test', session=session)
        data = completion._load_cache()
        assert set(data['keys']) == {'a', 'b', 'c'}
        assert data['folders'] == ['docs']

    def test_sync_deduplicates_saved_and_drops(self):
        session = self._mock_session(
            drops=[{'key': 'x'}],
            saved=[{'key': 'x'}],
            folders=[],
        )
        completion.sync_completions(host='https://drp.test', session=session)
        assert completion._load_cache()['keys'] == ['x']

    def test_sync_no_session_file_noops(self, tmp_path, monkeypatch):
        """Without a session file, sync_completions should silently no-op."""
        from cli import session as session_mod
        fake_session = tmp_path / 'no_such_session.json'
        monkeypatch.setattr(session_mod, 'SESSION_FILE', fake_session)
        # Should not crash
        completion.sync_completions()
        assert completion._load_cache() == {'keys': [], 'folders': []}

    def test_sync_server_error_noops(self):
        s = MagicMock()
        r = MagicMock()
        r.ok = False
        r.status_code = 500
        s.get.return_value = r
        completion.sync_completions(host='https://drp.test', session=s)
        assert completion._load_cache() == {'keys': [], 'folders': []}


# ══════════════════════════════════════════════════════════════════════════════
# _maybe_background_refresh — staleness gating
# ══════════════════════════════════════════════════════════════════════════════

class TestBackgroundRefresh:
    def test_fresh_cache_no_refresh(self, _isolate_cache):
        """If cache is fresh (<_STALE_SECS old), no thread is spawned."""
        completion._save_cache({'keys': [], 'folders': []})
        with patch('threading.Thread') as mock_thread:
            completion._maybe_background_refresh()
        mock_thread.assert_not_called()

    def test_stale_cache_triggers_refresh(self, _isolate_cache):
        """If cache is older than _STALE_SECS, a thread should be spawned."""
        completion._save_cache({'keys': [], 'folders': []})
        # Make it look old
        old_time = time.time() - completion._STALE_SECS - 10
        os.utime(str(_isolate_cache), (old_time, old_time))
        with patch('threading.Thread') as mock_thread:
            mock_thread.return_value.start = MagicMock()
            completion._maybe_background_refresh()
        mock_thread.assert_called_once()

    def test_missing_cache_triggers_refresh(self):
        """No cache file at all should trigger refresh."""
        with patch('threading.Thread') as mock_thread:
            mock_thread.return_value.start = MagicMock()
            completion._maybe_background_refresh()
        mock_thread.assert_called_once()
