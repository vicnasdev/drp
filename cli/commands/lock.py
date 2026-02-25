"""
drp lock — set or remove a password on an existing drop.

  drp lock <key>                   prompt for password interactively
  drp lock <key> --password pw     set password directly
  drp lock <key> --remove          remove password protection
  drp lock -f <key>                lock a file drop
"""

import getpass
import sys

from cli import api
from cli.commands._context import load_context
from cli.spinner import Spinner


def cmd_lock(args):
    cfg, host, session = load_context(require_login=True)

    key = args.key
    ns = 'f' if getattr(args, 'file', False) else 'c'
    prefix = f'/f/{key}/' if ns == 'f' else f'/{key}/'

    if getattr(args, 'remove', False):
        password = ''
    else:
        password = getattr(args, 'password', None)
        if password == '__prompt__' or password is None:
            try:
                password = getpass.getpass(f'  Password for {prefix}: ')
                if not password.strip():
                    print('  ✗ Password cannot be empty. Use --remove to remove.', file=sys.stderr)
                    sys.exit(1)
            except (KeyboardInterrupt, EOFError):
                print()
                return

    url = f'{host}{prefix}set-password/'
    try:
        from cli.api.auth import get_csrf
        csrf = get_csrf(host, session)
        with Spinner('updating'):
            resp = session.post(
                url,
                json={'password': password},
                headers={
                    'X-CSRFToken': csrf,
                    'Content-Type': 'application/json',
                },
                timeout=15,
            )
    except Exception as exc:
        print(f'  ✗ Network error: {exc}', file=sys.stderr)
        sys.exit(1)

    if resp.status_code == 403:
        data = _json_or(resp)
        print(f'  ✗ {data.get("error", "Permission denied — paid feature.")}', file=sys.stderr)
        sys.exit(1)

    if resp.status_code == 404:
        print(f'  ✗ Drop {prefix} not found.', file=sys.stderr)
        sys.exit(1)

    if not resp.ok:
        data = _json_or(resp)
        print(f'  ✗ {data.get("error", f"Server returned {resp.status_code}")}', file=sys.stderr)
        sys.exit(1)

    data = _json_or(resp)
    msg = data.get('message', '')
    if password:
        from cli.format import green
        print(f'  {green("✓")} {msg or "Password set."}')
    else:
        from cli.format import yellow
        print(f'  {yellow("✓")} {msg or "Password removed."}')


def _json_or(resp):
    try:
        return resp.json()
    except Exception:
        return {}
