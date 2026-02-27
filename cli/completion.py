"""
cli/completion.py

Shell tab-completion for drp.

Architecture
────────────
Tab-completion reads from a single local cache file:

    ~/.config/drp/completions.json

This file is a compact JSON dict:

    {"keys": ["hello", "notes", ...], "folders": ["docs", "work", ...]}

The cache is populated/refreshed:
  1. By `sync_completions()` — called after every mutating command
     (up, rm, mv, cp, mkdir, save, login). Fetches /auth/account/ and
     writes the file atomically.
  2. By `_read_and_maybe_refresh()` — if the cache is stale (>60s) when
     tab is pressed, a background thread fires a one-shot refresh.

Tab-press itself is always fast (<1ms) — it just reads the file.

Usage (in drp.py):
    import argcomplete
    from cli.completion import key_completer
    ...
    p_get.add_argument('key').completer = key_completer
    argcomplete.autocomplete(parser)
"""

import json
import os
import tempfile
import threading
import time
from pathlib import Path

from cli import config

COMPLETIONS_FILE = config.CONFIG_DIR / 'completions.json'

# How old the cache can be before a background refresh is triggered (seconds).
_STALE_SECS = 60


# ══════════════════════════════════════════════════════════════════════════════
# Public completers — wired to argparse arguments via argcomplete
# ══════════════════════════════════════════════════════════════════════════════

def key_completer(prefix, parsed_args, **kwargs):
    """Complete drop keys (for argcomplete)."""
    return _complete_keys(prefix)


def any_key_completer(prefix, parsed_args, **kwargs):
    """Alias for key_completer."""
    return _complete_keys(prefix)


def folder_slug_completer(prefix, parsed_args, **kwargs):
    """Complete folder slugs (for argcomplete)."""
    return _complete_folders(prefix)


# ══════════════════════════════════════════════════════════════════════════════
# Read cache — used by both argcomplete and the interactive shell
# ══════════════════════════════════════════════════════════════════════════════

def _load_cache() -> dict:
    """Load completions.json. Returns {'keys': [...], 'folders': [...]}."""
    try:
        if COMPLETIONS_FILE.exists():
            return json.loads(COMPLETIONS_FILE.read_text())
    except Exception:
        pass
    return {'keys': [], 'folders': []}


def _read_cache(prefix: str) -> list[str]:
    """Return drop keys matching *prefix*. Never raises."""
    try:
        data = _load_cache()
        return [k for k in data.get('keys', []) if k.startswith(prefix)]
    except Exception:
        return []


def _read_folder_cache(prefix: str) -> list[str]:
    """Return folder slugs matching *prefix*. Never raises."""
    try:
        data = _load_cache()
        return [s for s in data.get('folders', []) if s.startswith(prefix)]
    except Exception:
        return []


def _complete_keys(prefix: str) -> list[str]:
    """Read cache, maybe trigger background refresh, return matching keys."""
    keys = _read_cache(prefix)
    _maybe_background_refresh()
    return keys


def _complete_folders(prefix: str) -> list[str]:
    """Read cache, maybe trigger background refresh, return matching slugs."""
    slugs = _read_folder_cache(prefix)
    _maybe_background_refresh()
    return slugs


# ══════════════════════════════════════════════════════════════════════════════
# Write cache — atomic write via tempfile + rename
# ══════════════════════════════════════════════════════════════════════════════

def _save_cache(data: dict) -> None:
    """Atomically write completions.json (tmp + rename)."""
    try:
        COMPLETIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            dir=str(COMPLETIONS_FILE.parent),
            suffix='.tmp',
        )
        try:
            os.write(fd, json.dumps(data).encode())
            os.close(fd)
            os.replace(tmp, str(COMPLETIONS_FILE))
        except Exception:
            os.close(fd) if not os.get_inheritable(fd) else None
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except Exception:
        pass  # completions are never critical


# ══════════════════════════════════════════════════════════════════════════════
# Sync — called after mutating commands
# ══════════════════════════════════════════════════════════════════════════════

def sync_completions(host: str = None, session=None) -> None:
    """
    Fetch the current drop/folder list from the server and write the cache.

    Called after mutating commands (up, rm, mv, cp, mkdir, save, login).
    If host/session aren't provided, loads them from config/session files.

    Runs synchronously but is fast (single GET, compact response).
    Silently no-ops on any error.
    """
    try:
        if not host or not session:
            import requests as req_lib
            from cli.session import load_session, SESSION_FILE
            if not SESSION_FILE.exists():
                return
            cfg = config.load()
            host = host or cfg.get('host')
            if not host:
                return
            session = req_lib.Session()
            load_session(session)

        res = session.get(
            f'{host}/auth/account/',
            headers={'Accept': 'application/json'},
            timeout=8,
        )
        if not res.ok:
            return

        data = res.json()
        keys = []
        for d in data.get('drops', []):
            k = d.get('key', '')
            if k:
                keys.append(k)
        for s in data.get('saved', []):
            k = s.get('key', '')
            if k and k not in keys:
                keys.append(k)

        folders = []
        for f in data.get('folders', []):
            slug = f.get('slug', '')
            if slug:
                folders.append(slug)

        _save_cache({'keys': keys, 'folders': folders})

    except Exception:
        pass  # never crash on completion sync


def record_key(key: str) -> None:
    """Add a key to the cache immediately (no network). Used after upload."""
    try:
        data = _load_cache()
        keys = data.get('keys', [])
        if key not in keys:
            keys.insert(0, key)
        data['keys'] = keys
        _save_cache(data)
    except Exception:
        pass


def remove_key(key: str) -> None:
    """Remove a key from the cache immediately. Used after delete."""
    try:
        data = _load_cache()
        data['keys'] = [k for k in data.get('keys', []) if k != key]
        _save_cache(data)
    except Exception:
        pass


def rename_key(old: str, new: str) -> None:
    """Rename a key in the cache. Used after mv/rekey."""
    try:
        data = _load_cache()
        keys = data.get('keys', [])
        data['keys'] = [new if k == old else k for k in keys]
        _save_cache(data)
    except Exception:
        pass


def record_folder(slug: str) -> None:
    """Add a folder slug to the cache immediately. Used after mkdir."""
    try:
        data = _load_cache()
        folders = data.get('folders', [])
        if slug not in folders:
            folders.insert(0, slug)
        data['folders'] = folders
        _save_cache(data)
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
# Background refresh — only for stale cache during tab-press
# ══════════════════════════════════════════════════════════════════════════════

def _maybe_background_refresh() -> None:
    """If the cache is old, fire a one-shot daemon thread to refresh it."""
    try:
        if COMPLETIONS_FILE.exists():
            age = time.time() - COMPLETIONS_FILE.stat().st_mtime
            if age < _STALE_SECS:
                return
        t = threading.Thread(target=_bg_refresh, daemon=True)
        t.start()
    except Exception:
        pass


def _bg_refresh() -> None:
    """Background worker — just calls sync_completions()."""
    try:
        sync_completions()
    except Exception:
        pass
