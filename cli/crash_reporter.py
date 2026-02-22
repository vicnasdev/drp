"""
cli/crash_reporter.py

Silent crash reporter — sends sanitized error info to the drp server,
which files a GitHub issue if one doesn't already exist.

Coverage:
  • Unhandled exceptions in any cmd_* (wired in drp.py)
  • Handled HTTP errors in any API call (call report_http_error())
  • Silent outcome failures (call report_outcome())

What IS sent:
  - Exception type and scrubbed message
  - Scrubbed traceback (file paths + line numbers only, no variable values)
  - CLI version, Python version, OS platform
  - Command name only

What is NEVER sent:
  - Command arguments or flag values
  - Drop keys, content, or filenames from the user's machine
  - Email addresses, tokens, or auth data
  - Home-directory paths
"""

import platform
import re
import sys
import traceback as tb

# ── Scrub patterns ────────────────────────────────────────────────────────────

_SCRUB = [
    # Email addresses
    (re.compile(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+'), '[email]'),
    # URLs (may contain tokens or keys in query strings)
    (re.compile(r'https?://[^\s\'"]+'), '[url]'),
    # Unix home paths
    (re.compile(r'/home/[^/\s]+'), '/home/[user]'),
    (re.compile(r'/Users/[^/\s]+'), '/Users/[user]'),
    # Windows home paths
    (re.compile(r'C:\\Users\\[^\\]+'), r'C:\\Users\\[user]'),
    # Auth credentials in any form
    (re.compile(r"(?:password|token|secret|key|api[-_]?key)['\"]?\s*[:=]\s*['\"]?\S+", re.I),
     '[redacted]'),
]


def _scrub(text: str) -> str:
    for pat, rep in _SCRUB:
        text = pat.sub(rep, text)
    return text


def _safe_traceback(exc) -> list[str]:
    """Return scrubbed traceback lines — file paths + line numbers only."""
    if exc.__traceback__ is None:
        return []
    lines = tb.format_tb(exc.__traceback__)
    cleaned = []
    for chunk in lines:
        for line in chunk.splitlines(keepends=True):
            stripped = line.strip()
            if (stripped.startswith('File')
                    or stripped.startswith('^')
                    or stripped == ''):
                cleaned.append(_scrub(line))
            elif not any(c in line for c in ('=', '->', ': ')):
                cleaned.append(_scrub(line))
    return cleaned


# ── Public API ────────────────────────────────────────────────────────────────

def report(command: str, exc: Exception) -> None:
    """
    Report an unhandled exception.
    Call this from the main dispatch loop in drp.py (already wired) or from
    any command that catches and re-raises.
    """
    _send({
        'command':        command,
        'exc_type':       type(exc).__name__,
        'exc_message':    _scrub(str(exc)),
        'traceback':      _safe_traceback(exc),
        'cli_version':    _version(),
        'python_version': sys.version.split()[0],
        'platform':       platform.system(),
    })



def report_http_error(command: str, status_code: int, context: str = '') -> None:
    """
    Report a non-OK HTTP response that caused a handled early return.

    Usage (in any api/* or command):
        if not res.ok:
            from cli.crash_reporter import report_http_error
            report_http_error('rm', res.status_code, 'delete clipboard')
            ...
    """
    exc_type = f'HTTP{status_code}'
    msg = f'Server returned {status_code}'
    if context:
        msg += f' during {_scrub(context)}'
    _send({
        'command':        command,
        'exc_type':       exc_type,
        'exc_message':    msg,
        'traceback':      [],
        'cli_version':    _version(),
        'python_version': sys.version.split()[0],
        'platform':       platform.system(),
    })


def report_outcome(command: str, description: str) -> None:
    """
    Report a silent failure — an operation that returned False / gave a bad
    result without raising.  Examples: hard_delete() returned False (server
    said success but drop still accessible), upload_text() returned None.

    Usage:
        result_key = api.delete(host, session, key)
        if not result_key:
            from cli.crash_reporter import report_outcome
            report_outcome('rm', 'delete returned False for clipboard drop')
    """
    _send({
        'command':        command,
        'exc_type':       'SilentFailure',
        'exc_message':    _scrub(description),
        'traceback':      [],
        'cli_version':    _version(),
        'python_version': sys.version.split()[0],
        'platform':       platform.system(),
    })


# ── Internal helpers ──────────────────────────────────────────────────────────

def _version() -> str:
    try:
        from cli import __version__
        return __version__
    except Exception:
        return 'unknown'


def _send(payload: dict) -> None:
    """Fire-and-forget POST to /api/report-error/. Never raises."""
    try:
        import os
        if os.environ.get('PYTEST_CURRENT_TEST'):
            return
        import requests
        from cli import config
        cfg = config.load()
        host = cfg.get('host')
        if not host:
            return
        requests.post(
            f'{host}/api/report-error/',
            json=payload,
            timeout=3,
        )
    except Exception:
        pass  # never let the reporter interfere with the CLI