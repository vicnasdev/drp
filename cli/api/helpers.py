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