"""
Config management for the drp CLI.

Stores host and email in ~/.config/drp/config.json.
Local drop history is stored in ~/.config/drp/drops.json for anonymous users.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

CONFIG_DIR = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'drp'
CONFIG_FILE = CONFIG_DIR / 'config.json'
DROPS_FILE = CONFIG_DIR / 'drops.json'


def load(path=None):
    """Load config from disk. Returns empty dict if missing."""
    p = Path(path) if path else CONFIG_FILE
    if p.exists():
        return json.loads(p.read_text())
    return {}


def save(cfg, path=None):
    """Save config to disk, creating parent dirs if needed."""
    p = Path(path) if path else CONFIG_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, indent=2) + '\n')


# ── Local drop list (anonymous / offline cache) ───────────────────────────────

def load_local_drops():
    """Load the local drop list. Returns list of dicts."""
    if DROPS_FILE.exists():
        try:
            return json.loads(DROPS_FILE.read_text())
        except Exception:
            return []
    return []


def save_local_drops(drops):
    """Persist the local drop list."""
    DROPS_FILE.parent.mkdir(parents=True, exist_ok=True)
    DROPS_FILE.write_text(json.dumps(drops, indent=2) + '\n')


def record_drop(key, kind, ns='c', filename=None, host=None):
    """Add or update a drop in the local list."""
    drops = load_local_drops()
    # Remove any existing entry for this key
    drops = [d for d in drops if d.get('key') != key]
    entry = {
        'key': key,
        'kind': kind,
        'ns': ns,
        'created_at': datetime.now(timezone.utc).isoformat(),
        'host': host or '',
    }
    if filename:
        entry['filename'] = filename
    drops.insert(0, entry)
    save_local_drops(drops)


def remove_local_drop(key):
    """Remove a drop from the local list."""
    drops = [d for d in load_local_drops() if d.get('key') != key]
    save_local_drops(drops)


def rename_local_drop(old_key, new_key):
    """Update a key in the local list."""
    drops = load_local_drops()
    for d in drops:
        if d.get('key') == old_key:
            d['key'] = new_key
    save_local_drops(drops)
    