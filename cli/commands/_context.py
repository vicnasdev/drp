"""
cli/commands/_context.py

Shared bootstrap for CLI commands: load config, resolve host, build session.
Replaces the 6-line boilerplate that was copy-pasted into every command.
"""

import os
import sys

import requests

from cli import config
from cli.session import auto_login


def load_context(require_login=False):
    """
    Load config, validate host, build an authenticated session.

    If DRP_API_KEY is set, use Bearer token auth instead of session cookies.

    Returns (cfg, host, session).
    Exits with a clear message if not configured or (when require_login=True)
    if no account is logged in.
    """
    cfg = config.load()
    host = cfg.get('host')
    if not host:
        print('  ✗ Not configured. Run: drp setup')
        sys.exit(1)

    session = requests.Session()

    api_key = os.environ.get("DRP_API_KEY", "").strip() or cfg.get("api_key", "")
    if api_key:
        session.headers["Authorization"] = f"Bearer {api_key}"
    else:
        auto_login(cfg, host, session)
        if require_login and not cfg.get('email'):
            print('  ✗ Login required. Run: drp login')
            sys.exit(1)

    return cfg, host, session
