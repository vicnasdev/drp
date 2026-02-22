"""
cli/commands/_context.py

Shared bootstrap for CLI commands: load config, resolve host, build session.
Replaces the 6-line boilerplate that was copy-pasted into every command.
"""

import sys

import requests

from cli import config
from cli.session import auto_login


def load_context(require_login=False):
    """
    Load config, validate host, build an authenticated session.

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
    auto_login(cfg, host, session)
    if require_login and not cfg.get('email'):
        print('  ✗ Login required. Run: drp login')
        sys.exit(1)
    return cfg, host, session
