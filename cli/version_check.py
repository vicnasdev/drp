"""
Background version-check for the drp CLI.

Periodically queries PyPI for the latest published version and caches the
result locally.  The check runs in a daemon thread so it never blocks the
actual command.  A notice is printed *after* the command finishes only when
a newer version is available.

Timing:
  • At most once every CHECK_INTERVAL_HOURS (default 24 h).
  • PyPI request has a 3-second timeout — worst case it silently fails.
  • The cache file (~/.config/drp/version_check.json) persists across runs.

Usage (in cli/drp.py main()):
    checker = start_check()
    ...run the command...
    show_notice(checker)
"""

import json
import os
import threading
import time
from pathlib import Path

from cli import __version__
from cli.config import CONFIG_DIR

CHECK_INTERVAL_HOURS = 24
CACHE_FILE = CONFIG_DIR / "version_check.json"
_TIMEOUT = 3  # seconds


def _detect_package_name() -> str:
    """Return the installed package name ('drp-cli' or 'drp')."""
    from importlib.metadata import version
    for name in ('drp-cli', 'drp'):
        try:
            version(name)
            return name
        except Exception:
            continue
    return 'drp-cli'  # fallback


PACKAGE_NAME = _detect_package_name()
PYPI_URL = f"https://pypi.org/pypi/{PACKAGE_NAME}/json"


# ── Cache ─────────────────────────────────────────────────────────────────────

def _read_cache() -> dict:
    try:
        return json.loads(CACHE_FILE.read_text())
    except Exception:
        return {}


def _write_cache(latest: str):
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps({
            "last_checked": time.time(),
            "latest_version": latest,
        }))
    except Exception:
        pass  # non-critical


def _should_check(cache: dict) -> bool:
    """Return True if enough time has elapsed since the last check."""
    last = cache.get("last_checked", 0)
    return (time.time() - last) >= CHECK_INTERVAL_HOURS * 3600


# ── Version comparison ────────────────────────────────────────────────────────

def _parse_version(v: str):
    """Parse 'x.y.z' into a tuple of ints for comparison."""
    try:
        return tuple(int(p) for p in v.strip().split("."))
    except (ValueError, AttributeError):
        return (0,)


def is_newer(latest: str, current: str) -> bool:
    """Return True if latest > current."""
    return _parse_version(latest) > _parse_version(current)


# ── PyPI fetch ────────────────────────────────────────────────────────────────

def _fetch_latest() -> str | None:
    """Query PyPI for the latest version.  Returns version string or None."""
    try:
        import requests
        resp = requests.get(PYPI_URL, timeout=_TIMEOUT)
        if resp.ok:
            return resp.json().get("info", {}).get("version")
    except Exception:
        pass
    return None


# ── Public API ────────────────────────────────────────────────────────────────

class VersionChecker:
    """Holds the background thread result."""

    def __init__(self):
        self.latest: str | None = None
        self._thread: threading.Thread | None = None

    def _run(self):
        cache = _read_cache()
        if not _should_check(cache):
            # Use cached value
            self.latest = cache.get("latest_version")
            return
        latest = _fetch_latest()
        if latest:
            self.latest = latest
            _write_cache(latest)

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def join(self, timeout: float = 0.05):
        """Wait briefly for the thread to finish (default 50 ms)."""
        if self._thread:
            self._thread.join(timeout=timeout)


def start_check() -> VersionChecker:
    """Launch the background version check.  Returns a VersionChecker."""
    checker = VersionChecker()
    # Skip entirely if DRP_NO_UPDATE_CHECK or CI
    if os.environ.get("DRP_NO_UPDATE_CHECK") or os.environ.get("CI"):
        return checker
    checker.start()
    return checker


def show_notice(checker: VersionChecker):
    """Print an upgrade notice if a newer version is available."""
    if checker.latest and is_newer(checker.latest, __version__):
        from cli.format import dim, yellow
        print(f"\n  {yellow('update available')} {dim(__version__)} → {checker.latest}")
        print(f"  {dim(f'pipx upgrade {PACKAGE_NAME}')}")
