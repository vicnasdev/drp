"""
Small utilities shared across CLI API modules.
"""

import sys
from pathlib import Path


def slug(name):
    """Turn a filename into a url-safe slug (max 40 chars)."""
    import secrets
    import re
    stem = Path(name).stem
    safe = ''.join(c if c.isalnum() or c in '-_' else '-' for c in stem).strip('-')
    safe = re.sub(r'-{2,}', '-', safe)  # collapse consecutive hyphens
    return safe[:40] or secrets.token_urlsafe(6)


def err(msg):
    """Print a formatted error to stderr."""
    from cli.format import red
    print(f'  {red("✗", stream=sys.stderr)} {msg}', file=sys.stderr)


def ok(msg):
    """Print a formatted success message."""
    from cli.format import green
    print(f'  {green("✓")} {msg}')


# ── Shared HTTP helpers (used by text.py, file.py, actions.py) ────────────────

def touch_session():
    """Bump session file mtime to keep it alive."""
    try:
        from cli.session import SESSION_FILE
        SESSION_FILE.touch()
    except Exception:
        pass


def handle_error(res, prefix):
    """Extract error message from a failed response and print it."""
    try:
        msg = res.json().get('error', res.text[:200])
    except Exception:
        msg = res.text[:200]
    err(f'{prefix}: {msg}')


def handle_http_error(res, key):
    """Print a human-readable error for common HTTP status codes."""
    if res.status_code == 404:
        err(f'Drop /{key}/ not found.')
    elif res.status_code == 410:
        err(f'Drop /{key}/ has expired.')
    else:
        err(f'Server returned {res.status_code}.')


def report_crash(command, msg):
    """Fire-and-forget crash report — never raises."""
    try:
        from cli.crash_reporter import report
        report(command, RuntimeError(msg))
    except Exception:
        pass


def report_http(command, status_code, context):
    """Fire-and-forget HTTP error report — never raises."""
    try:
        from cli.crash_reporter import report_http_error
        report_http_error(command, status_code, context)
    except Exception:
        pass