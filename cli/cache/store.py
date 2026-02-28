"""
cli/cache/store.py

Local key cache — persists keys the user has interacted with so that
`drp ls` outside the shell is instant and offline-capable.

Stored at ~/.config/drp/cache.toml as a flat list of drop records.
Each record mirrors the columns shown in `ls`: filename, size, exp, key, owner.

Cache is append-only from the CLI side. Server-side expiry is not tracked
here — stale entries are shown dimmed with `exp: ?` until the user runs
`drp status <key>` to refresh.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from cli.config.settings import CONFIG_DIR

try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib             # type: ignore[no-redef]
    except ImportError:
        tomllib = None                      # type: ignore[assignment]

try:
    import tomli_w
except ImportError:
    tomli_w = None                          # type: ignore[assignment]


CACHE_FILE = CONFIG_DIR / "cache.toml"


def all_entries() -> list[dict]:
    """Return all cached drops, newest first."""
    return list(reversed(_load()))


def add(entry: dict) -> None:
    """
    Add or update a drop in the cache.
    entry keys: key, filename, size, exp (ISO str or None), owner (or "")
    """
    entries = _load()
    entries = [e for e in entries if e.get("key") != entry.get("key")]
    entry.setdefault("cached_at", datetime.now(timezone.utc).isoformat())
    entries.append(entry)
    _save(entries)


def remove(key: str) -> None:
    entries = [e for e in _load() if e.get("key") != key]
    _save(entries)


def get(key: str) -> dict | None:
    return next((e for e in _load() if e.get("key") == key), None)


# ------------------------------------------------------------------ internal

def _load() -> list[dict]:
    if not CACHE_FILE.exists() or tomllib is None:
        return []
    try:
        with open(CACHE_FILE, "rb") as f:
            data = tomllib.load(f)
        return data.get("drops", [])
    except Exception:
        return []


def _save(entries: list[dict]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if tomli_w is not None:
        with open(CACHE_FILE, "wb") as f:
            tomli_w.dump({"drops": entries}, f)
    else:
        # Minimal fallback — writes enough for round-trip.
        # FIX: the original started lines=["[[drops]]"] before the loop, which
        # wrote an orphan empty [[drops]] header that parsed as a ghost empty
        # entry {}. This made all_entries() return [{real}, {}], and on the next
        # add() call the ghost entry was re-saved alongside the real ones,
        # growing the file with a phantom record on every write. Starting lines=[]
        # and only emitting [[drops]] inside the loop fixes both problems.
        lines = []
        for e in entries:
            lines.append("[[drops]]")
            for k, v in e.items():
                if v is None:
                    continue
                if isinstance(v, bool):
                    lines.append(f"{k} = {'true' if v else 'false'}")
                elif isinstance(v, str):
                    escaped = v.replace("\\", "\\\\").replace('"', '\\"')
                    lines.append(f'{k} = "{escaped}"')
                else:
                    lines.append(f"{k} = {v}")
            lines.append("")  # blank line between entries for readability
        CACHE_FILE.write_text("\n".join(lines), encoding="utf-8")