"""
drp switch — convert a drop between text and file.

  drp switch <key>            switch clipboard text → file (or file → text)
  drp switch -f <key>         switch a file drop → clipboard text
"""

import sys

from cli.commands._context import load_context
from cli.api.auth import get_csrf
from cli.api.helpers import err


def _url(host, ns, key):
    if ns == 'f':
        return f'{host}/f/{key}/switch/'
    return f'{host}/{key}/switch/'


def cmd_switch(args):
    cfg, host, session = load_context()

    ns = 'f' if getattr(args, 'file', False) and not getattr(args, 'clip', False) else 'c'

    # If user didn't specify -f/-c, auto-detect from local drop cache
    if not getattr(args, 'file', False) and not getattr(args, 'clip', False):
        from cli.config import load_local_drops
        try:
            for d in load_local_drops():
                if d.get('key') == args.key:
                    ns = d.get('ns', 'c')
                    break
        except Exception:
            pass

    payload = {}
    if getattr(args, 'filename', None):
        payload['filename'] = args.filename

    from cli.spinner import Spinner
    with Spinner('switching'):
        csrf = get_csrf(host, session)
        try:
            res = session.post(
                _url(host, ns, args.key),
                data=payload,
                headers={'X-CSRFToken': csrf},
                timeout=30,
            )
        except Exception as e:
            err(f'Switch error: {e}')
            sys.exit(1)

    if res.ok:
        data = res.json()
        new_kind = data.get('kind', '?')
        new_key = data.get('key', args.key)
        url = data.get('url', '')
        filename = data.get('filename', '')

        old_prefix = 'f/' if ns == 'f' else ''
        new_prefix = 'f/' if data.get('ns') == 'f' else ''

        print(f'  ✓ /{old_prefix}{args.key}/ → /{new_prefix}{new_key}/')
        if filename:
            print(f'    filename: {filename}')
        print(f'    {host}{url}')

        # Update local drop cache
        from cli import config as cfg_mod
        cfg_mod.remove_local_drop(args.key)
        cfg_mod.record_drop(new_key, new_kind, ns=data.get('ns', 'c'), host=host)
    elif res.status_code == 400:
        try:
            msg = res.json().get('error', res.text[:200])
        except Exception:
            msg = res.text[:200]
        err(msg)
        sys.exit(1)
    elif res.status_code == 404:
        err(f'Drop /{args.key}/ not found.')
        sys.exit(1)
    elif res.status_code == 401:
        err('Login required — run: drp login')
        sys.exit(1)
    elif res.status_code == 403:
        try:
            msg = res.json().get('error', 'Forbidden')
        except Exception:
            msg = 'Forbidden'
        err(msg)
        sys.exit(1)
    else:
        try:
            msg = res.json().get('error', res.text[:200])
        except Exception:
            msg = res.text[:200]
        err(f'Switch failed: {msg}')
        sys.exit(1)
