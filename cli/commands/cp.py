"""
drp cp — duplicate a drop under a new key.

  drp cp <key> <new-key>        copy clipboard drop
  drp cp -f <key> <new-key>     copy file drop (server-side B2 copy, no re-upload)
"""

import sys

from cli.commands._context import load_context
from cli.api.auth import get_csrf
from cli.api.helpers import err


def _url(host, ns, key):
    if ns == 'f':
        return f'{host}/f/{key}/copy/'
    return f'{host}/{key}/copy/'


def cmd_cp(args):
    cfg, host, session = load_context()

    ns = 'f' if getattr(args, 'file', False) and not getattr(args, 'clip', False) else 'c'

    from cli.spinner import Spinner
    with Spinner('copying'):
        csrf = get_csrf(host, session)
        try:
            res = session.post(
                _url(host, ns, args.key),
                json={'new_key': args.new_key},
                headers={'X-CSRFToken': csrf, 'Content-Type': 'application/json'},
                timeout=30,
            )
        except Exception as e:
            err(f'Copy error: {e}')
            sys.exit(1)

    if res.ok:
        data = res.json()
        new_key = data['key']
        prefix  = 'f/' if ns == 'f' else ''
        print(f'  ✓ /{prefix}{args.key}/ → /{prefix}{new_key}/')
        print(f'    {host}/{prefix}{new_key}/')

        from cli import config as cfg_mod
        kind = 'file' if ns == 'f' else 'text'
        cfg_mod.record_drop(new_key, kind, ns=ns, host=host)
    elif res.status_code == 409:
        err(f'Key "{args.new_key}" is already taken.')
        sys.exit(1)
    elif res.status_code == 404:
        err(f'Drop /{args.key}/ not found.')
        sys.exit(1)
    else:
        try:
            msg = res.json().get('error', res.text[:200])
        except Exception:
            msg = res.text[:200]
        err(f'Copy failed: {msg}')
        sys.exit(1)
