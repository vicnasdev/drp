"""
Pure logic for GitHub issue filing — no Django dependency.
Imported by both core/views/error_reporting.py and the test suite.

Deduplication strategy
──────────────────────
Issues are deduplicated by a *fingerprint* — a short SHA-1 hash of:

    exc_type + normalized traceback

"Normalized" means:
  - Line numbers stripped   → same bug after a version bump still matches
  - File paths shortened    → same bug triggered from a different command still matches
  - [locals redacted] lines dropped

The fingerprint is embedded in every issue body as an HTML comment:

    <!-- drp-fingerprint: a3f9c12b8e01 -->

Before creating an issue, _issue_exists() fetches all open auto-reported
issues and scans their bodies for matching fingerprints.  Title and command
name are irrelevant for deduplication — the same underlying bug reported
from `drp upload` and `drp serve` will correctly match the same open issue.
"""

import hashlib
import logging
import os
import re
import threading

import requests as http

logger = logging.getLogger(__name__)

GITHUB_TOKEN = os.environ.get('GITHUB_ISSUES_TOKEN', '')
GITHUB_REPO  = os.environ.get('GITHUB_REPO', 'vicnasdev/drp')
GITHUB_API   = 'https://api.github.com'

# Maximum number of open auto-reported issues before the flood guard kicks in.
_FLOOD_LIMIT = 20

# Lock to prevent concurrent threads from creating duplicate issues.
_FILING_LOCK = threading.Lock()

# Regex to extract a fingerprint embedded in an issue body.
_FP_RE = re.compile(r'<!-- drp-fingerprint: ([a-f0-9]{12}) -->')


# ── Scrubber ──────────────────────────────────────────────────────────────────

_SCRUB_PATTERNS = [
    (re.compile(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+'), '[email]'),
    (re.compile(r'https?://[^\s\'"]+'), '[url]'),
    (re.compile(r'/home/[^/\s]+'), '/home/[user]'),
    (re.compile(r'/Users/[^/\s]+'), '/Users/[user]'),
    (re.compile(r'C:\\Users\\[^\\]+'), r'C:\\Users\\[user]'),
    (re.compile(r"password['\"]?\s*[:=]\s*['\"]?[^\s'\"]+", re.I), 'password=[redacted]'),
    (re.compile(r"token['\"]?\s*[:=]\s*['\"]?[^\s'\"]+", re.I), 'token=[redacted]'),
]

_LINENO_RE   = re.compile(r',\s*line\s+\d+')
_FILEPATH_RE = re.compile(r'"([^"]+)"')


def _scrub(text):
    for pattern, replacement in _SCRUB_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _scrub_traceback(lines):
    cleaned = []
    for line in lines:
        if line.strip().startswith('During handling') or \
           (' = ' in line and not line.strip().startswith('File')):
            cleaned.append('    [locals redacted]\n')
        else:
            cleaned.append(_scrub(line))
    return cleaned


# ── Fingerprinting ────────────────────────────────────────────────────────────

def _fingerprint(data: dict) -> str:
    """
    Return a 12-char hex fingerprint that is stable across:
      - which command triggered the error
      - CLI / Python version bumps
      - exact line number changes

    For exceptions with a traceback the fingerprint encodes:
      exc_type + the sequence of (short_file_path, function_name) pairs

    For HTTP errors and SilentFailure (no traceback) it encodes:
      exc_type alone — so all occurrences of e.g. HTTP403 share one issue
      regardless of which command produced it.
    """
    exc_type = data.get('exc_type', '')
    tb_lines = data.get('traceback', [])

    norm_parts = []
    for line in tb_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith('[locals'):
            continue
        if stripped.startswith('File'):
            # Drop line number: ', line 42'
            no_lineno = _LINENO_RE.sub('', stripped)
            # Shorten absolute path to last 3 components
            m = _FILEPATH_RE.search(no_lineno)
            if m:
                parts = m.group(1).replace('\\', '/').split('/')
                short = '/'.join(parts[-3:]) if len(parts) >= 3 else m.group(1)
                no_lineno = _FILEPATH_RE.sub(f'"{short}"', no_lineno, count=1)
            norm_parts.append(no_lineno)
        else:
            # Function / code lines — keep as-is (already scrubbed upstream)
            norm_parts.append(stripped)

    key = exc_type + ':' + '\n'.join(norm_parts)
    return hashlib.sha1(key.encode()).hexdigest()[:12]


# ── GitHub ────────────────────────────────────────────────────────────────────

def _issue_title(exc_type, command):
    return f'[auto] {exc_type} in `drp {command}`'


def _open_auto_issues() -> list[dict]:
    """Fetch all open auto-reported issues (handles pagination)."""
    if not GITHUB_TOKEN:
        return []
    issues = []
    page = 1
    while True:
        try:
            res = http.get(
                f'{GITHUB_API}/repos/{GITHUB_REPO}/issues',
                headers={
                    'Authorization': f'token {GITHUB_TOKEN}',
                    'Accept': 'application/vnd.github+json',
                },
                params={
                    'state': 'open',
                    'labels': 'bug,auto-reported',
                    'per_page': 100,
                    'page': page,
                },
                timeout=8,
            )
            if not res.ok:
                break
            page_issues = res.json()
            if not page_issues:
                break
            issues.extend(page_issues)
            # GitHub returns fewer than per_page when it's the last page
            if len(page_issues) < 100:
                break
            page += 1
        except Exception:
            break
    return issues


def _issue_exists(data: dict) -> bool:
    """
    Return True if an equivalent open issue already exists, or if the
    global flood guard has triggered.

    Deduplication is fingerprint-based: the same underlying bug reported
    from any command, any CLI version, or any line number will match.
    """
    if not GITHUB_TOKEN:
        return False

    fp = _fingerprint(data)
    open_issues = _open_auto_issues()

    # Flood guard — stop creating issues if there are already too many open.
    if len(open_issues) >= _FLOOD_LIMIT:
        logger.warning('drp auto-reporter: flood guard triggered (%d open issues)', len(open_issues))
        return True

    # Fingerprint match — scan every open issue body for our hidden comment.
    for issue in open_issues:
        body = issue.get('body') or ''
        m = _FP_RE.search(body)
        if m and m.group(1) == fp:
            return True

    return False


def _create_issue(title, body):
    if not GITHUB_TOKEN:
        logger.warning('GITHUB_ISSUES_TOKEN not set — skipping issue creation')
        return False
    try:
        res = http.post(
            f'{GITHUB_API}/repos/{GITHUB_REPO}/issues',
            headers={
                'Authorization': f'token {GITHUB_TOKEN}',
                'Accept': 'application/vnd.github+json',
            },
            json={'title': title, 'body': body, 'labels': ['bug', 'auto-reported']},
            timeout=8,
        )
        return res.status_code == 201
    except Exception as e:
        logger.error('Failed to create GitHub issue: %s', e)
        return False


def _build_body(data: dict) -> tuple[str, str]:
    """
    Return (title, body) for a new GitHub issue.

    The body embeds a hidden fingerprint comment so future reports of the
    same bug can be deduplicated without relying on the title.
    """
    exc_type    = _scrub(data.get('exc_type', 'Unknown'))
    exc_msg     = _scrub(data.get('exc_message', ''))
    tb_lines    = _scrub_traceback(data.get('traceback', []))
    cli_version = data.get('cli_version', '?')
    py_version  = data.get('python_version', '?')
    platform    = data.get('platform', '?')
    command     = data.get('command', '?')

    normalized = []
    for line in tb_lines:
        if not line.endswith('\n'):
            line = line + '\n'
        normalized.append(line)
    tb_text = ''.join(normalized) if normalized else '(none)'

    fp = _fingerprint(data)
    title = _issue_title(exc_type, command)

    body = f"""## `{exc_type}: {exc_msg}`

**Command:** `drp {command}`
**CLI:** `{cli_version}` · **Python:** `{py_version}` · **OS:** `{platform}`

```
{tb_text}
```

---
*Auto-reported by drp CLI. No user data included.*
<!-- drp-fingerprint: {fp} -->
"""
    return title, body


# ── Entry point called by core/views/error_reporting.py ──────────────────────

def maybe_file_issue(data: dict) -> bool:
    """
    Canonical entry point.  Returns True if an issue was created.

    Replaces the old pattern of calling _issue_exists / _create_issue
    separately so callers don't need to touch the internals.

    Uses a threading lock so concurrent 500 handlers don't race past
    the dedup check and create duplicate GitHub issues.
    """
    with _FILING_LOCK:
        if _issue_exists(data):
            return False
        title, body = _build_body(data)
        return _create_issue(title, body)