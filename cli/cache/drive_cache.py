"""
cli/cache/drive_cache.py

Local JSON cache of the user's drp drive tree.

Design goals
------------
* Autocomplete reads ONLY from memory — no I/O, no network, always instant.
* A single background thread keeps the cache fresh by polling a cheap
  /api/v1/drive/version/ endpoint (returns one hash string).  The full tree
  is only fetched when that hash changes.
* Any write command (up, cp, mv, mkdir, rm) calls invalidate() to force an
  immediate refresh so the next Tab press sees the new file/folder.
* The cache is saved to disk so it survives shell restarts without a full
  re-fetch on startup.

Cache file: ~/.config/drp/drive_cache.json
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from cli.config.settings import CONFIG_DIR

CACHE_FILE = CONFIG_DIR / "drive_cache.json"

# How often (seconds) the background thread checks the version endpoint.
POLL_INTERVAL = 30


# ---------------------------------------------------------------------------
# In-memory state (module-level so it's shared across all command instances)
# ---------------------------------------------------------------------------

_lock    = threading.Lock()
_version: str | None = None          # last version hash seen from server
_tree:    dict       = {}             # {cwd_id_or_"root": {"folders": [...], "items": [...]}}
_dirty:   threading.Event = threading.Event()   # set to wake the bg thread early


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def start(config: dict) -> None:
    """
    Load cache from disk, then start the background refresh thread.
    Call once at shell startup.
    """
    _load_from_disk()
    t = threading.Thread(target=_bg_loop, args=(config,), daemon=True, name="drp-cache")
    t.start()


def invalidate() -> None:
    """
    Signal that a write has occurred. The background thread will re-fetch
    the full tree on its next wake, which happens immediately.
    """
    global _version
    with _lock:
        _version = None          # force version mismatch on next check
    _dirty.set()                 # wake the thread immediately


def get_names(cwd_id: int | None) -> list[str]:
    """
    Return a list of names (folder slugs + filenames) for the given folder.
    Always reads from the in-memory cache — zero I/O, safe to call from a
    readline completer callback.
    """
    key = str(cwd_id) if cwd_id is not None else "root"
    with _lock:
        entry = _tree.get(key, {})
    names  = [f["slug"] + "/" for f in entry.get("folders", [])]
    names += [
        i.get("filename") or i.get("label") or i.get("key", "")
        for i in entry.get("items", [])
    ]
    return names


# ---------------------------------------------------------------------------
# Background thread
# ---------------------------------------------------------------------------

def _bg_loop(config: dict) -> None:
    """Poll the version endpoint; only fetch the full tree when it changes."""
    while True:
        _dirty.clear()
        try:
            _maybe_refresh(config)
        except Exception:
            pass
        # Sleep for POLL_INTERVAL, but wake immediately if invalidate() is called
        _dirty.wait(timeout=POLL_INTERVAL)


def _maybe_refresh(config: dict) -> None:
    global _version

    try:
        from cli.api.client import APIClient
        from cli.api import folders as folders_api
        client = APIClient.from_config(config, authed=True)
    except Exception:
        return

    # 1. Cheap version check
    try:
        resp    = client.get("/api/v1/drive/version/")
        server_version = resp.json().get("version") if resp.status_code == 200 else None
    except Exception:
        server_version = None

    with _lock:
        current = _version

    if server_version and server_version == current:
        return   # nothing changed

    # 2. Full tree fetch
    try:
        new_tree: dict = {}

        # Root level
        root = folders_api.list_root(client)
        new_tree["root"] = {
            "folders": root.get("folders", []),
            "items":   root.get("items", []),
        }

        # Recurse into every top-level folder (one level deep is enough for
        # autocomplete; deeper folders can be added lazily in future)
        for folder in root.get("folders", []):
            fid = folder.get("id")
            if fid is None:
                continue
            try:
                contents = folders_api.list_contents(client, fid)
                new_tree[str(fid)] = {
                    "folders": contents.get("folders", []),
                    "items":   contents.get("items", []),
                }
                # One more level
                for sub in contents.get("folders", []):
                    sid = sub.get("id")
                    if sid is None:
                        continue
                    try:
                        sc = folders_api.list_contents(client, sid)
                        new_tree[str(sid)] = {
                            "folders": sc.get("folders", []),
                            "items":   sc.get("items", []),
                        }
                    except Exception:
                        pass
            except Exception:
                pass

        with _lock:
            _tree.clear()
            _tree.update(new_tree)
            _version = server_version or str(time.monotonic())

        _save_to_disk()

    except Exception:
        pass


# ---------------------------------------------------------------------------
# Disk persistence
# ---------------------------------------------------------------------------

def _load_from_disk() -> None:
    global _version
    try:
        if CACHE_FILE.exists():
            data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            with _lock:
                _tree.update(data.get("tree", {}))
                _version = data.get("version")
    except Exception:
        pass


def _save_to_disk() -> None:
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with _lock:
            payload = {"version": _version, "tree": dict(_tree)}
        CACHE_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception:
        pass
