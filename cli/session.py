"""
Session persistence for the drp CLI.
Saves/loads cookies so users aren't prompted for a password on every command.
"""

import getpass
import json
import sys
import time

import requests

from cli import config, api

SESSION_FILE = config.CONFIG_DIR / 'session.json'

# If the session file was written within this many seconds, trust it without
# hitting the server to validate. Avoids a full Railway round-trip on every
# command. When the session does expire, the next real API call returns 302
# which auto_login already handles by re-prompting.
SESSION_CACHE_SECS = 3600  # 1 hour — long enough to cover a full test suite run

# ── Retry configuration ──────────────────────────────────────────────────────
# Covers short server downtimes (deploys, Railway cold starts, transient 502s).
# Total wall-time budget: ~120 s (1 + 2 + 4 + 8 + 16 + 32 + 57 ≈ 120).
RETRY_BACKOFF = [1, 2, 4, 8, 16, 32, 57]  # seconds between retries
RETRY_STATUS_CODES = frozenset({502, 503, 504})

_RETRIABLE = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
)


class ResilientSession(requests.Session):
    """requests.Session with transparent retry for transient failures.

    Retries on ConnectionError, Timeout, and 502/503/504 with exponential
    backoff. Total retry budget is ~120 s. Non-retryable errors propagate
    immediately.
    """

    def request(self, method, url, **kwargs):
        last_exc = None
        for attempt, wait in enumerate([0] + RETRY_BACKOFF):
            if wait:
                time.sleep(wait)
            try:
                resp = super().request(method, url, **kwargs)
                if resp.status_code in RETRY_STATUS_CODES and attempt < len(RETRY_BACKOFF):
                    last_exc = None
                    continue
                return resp
            except _RETRIABLE as exc:
                last_exc = exc
                continue
        # Exhausted retries — raise last exception or return last response
        if last_exc is not None:
            raise last_exc
        return resp  # noqa: the variable is always bound here


def ensure_authenticated(host, session, cfg):
    """Verify the session is actually valid; re-auth if the server rejected it.

    Call this after a request returns HTML instead of JSON (302 → login page).
    Invalidates the cache so auto_login takes the slow path and prompts if needed.
    Returns True if re-authenticated, False otherwise.
    """
    # Invalidate the cache so auto_login hits the server
    try:
        if SESSION_FILE.exists():
            import os
            os.utime(str(SESSION_FILE), (0, 0))
    except Exception:
        pass
    return auto_login(cfg, host, session, required=True)


def load_session(session):
    """Load saved cookies into session. Silent — never prompts."""
    if SESSION_FILE.exists():
        try:
            session.cookies.update(json.loads(SESSION_FILE.read_text()))
        except Exception:
            pass


def save_session(session):
    """Persist session cookies to disk."""
    config.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    SESSION_FILE.write_text(json.dumps(dict(session.cookies)) + '\n')


def clear_session():
    """Delete saved session."""
    if SESSION_FILE.exists():
        SESSION_FILE.unlink()


def _session_is_fresh() -> bool:
    try:
        if not SESSION_FILE.exists():
            return False
        age = time.time() - SESSION_FILE.stat().st_mtime
        return age < SESSION_CACHE_SECS
    except Exception:
        return False


def auto_login(cfg, host, session, required=False):
    """
    Load saved session and verify it's still valid.

    Fast path (session fresh): load cookies and return immediately — no
    network call, no spinner.

    Slow path (session stale): ping the server to validate. A spinner runs
    during this wait since it can take 1-2s on a cold Railway instance.
    """
    email = cfg.get('email')
    if not email:
        return False

    load_session(session)

    # Fast path: session file is recent — trust it without a network call.
    if _session_is_fresh():
        return True

    # Slow path: validate with the server — show a spinner for the wait.
    from cli.spinner import Spinner

    try:
        with Spinner('connecting'):
            res = session.get(
                f'{host}/auth/account/',
                headers={'Accept': 'application/json'},
                timeout=10,
                allow_redirects=False,
            )
        if res.status_code == 200:
            SESSION_FILE.touch()
            return True
    except Exception as e:
        print(f'  ✗ Could not reach {host}: {e}')
        if required:
            sys.exit(1)
        return False

    # Session expired — prompt once.
    try:
        password = getpass.getpass(f'  Session expired. Password for {email}: ')
    except (KeyboardInterrupt, EOFError):
        print()
        if required:
            sys.exit(1)
        return False

    try:
        if api.login(host, session, email, password):
            save_session(session)
            return True
    except Exception as e:
        print(f'  ✗ Login error: {e}')

    print('  ✗ Login failed. Continuing as anonymous.')
    if required:
        sys.exit(1)
    return False