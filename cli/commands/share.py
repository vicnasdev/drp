"""
drp share — manage sharing for drops and folders.

  drp share <key>                  print shareable link for a drop
  drp share <key> --folder         create a folder share token
  drp share <key> --revoke <tid>   revoke a share token
  drp share <key> --list           list active share tokens
"""

import json
import sys

from cli.commands._context import load_context
from cli.format import dim


def cmd_share(args):
    host, session, cfg = load_context()
    key = args.key

    if getattr(args, 'list', False):
        _list_tokens(host, session, key)
        return

    revoke_id = getattr(args, 'revoke', None)
    if revoke_id:
        _revoke_token(host, session, key, revoke_id)
        return

    if getattr(args, 'folder', False):
        _create_folder_token(host, session, key, args)
        return

    # Default: print shareable link for a drop
    url = f'{host}/{key}/'
    print(url)
    print(f'  {dim("share this link to give access")}')


def _create_folder_token(host, session, folder_id, args):
    from cli.api.auth import get_csrf
    csrf = get_csrf(host, session)
    hours = getattr(args, 'expires_hours', 24) or 24

    res = session.post(
        f'{host}/folders/{folder_id}/share/',
        json={'expires_hours': hours},
        headers={'X-CSRFToken': csrf, 'Referer': f'{host}/'},
        timeout=15,
    )
    if res.ok:
        data = res.json()
        print(data.get('share_url', ''))
        exp = data.get('expires_at', '')
        print(f'  {dim("token:")} {data.get("token", "?")}')
        if exp:
            print(f'  {dim("expires:")} {exp}')
    else:
        print(f'  ✗ {res.status_code}: {res.text}')
        sys.exit(1)


def _list_tokens(host, session, folder_id):
    res = session.get(
        f'{host}/folders/{folder_id}/share/list/',
        headers={'Accept': 'application/json'},
        timeout=15,
    )
    if not res.ok:
        print(f'  ✗ {res.status_code}: {res.text}')
        sys.exit(1)

    data = res.json()
    tokens = data.get('tokens', [])
    if not tokens:
        print('  no share tokens')
        return

    for t in tokens:
        status = '✗ expired' if t.get('expired') else '✓ active'
        print(f'  {t["id"]:>4}  {t["token"][:12]}…  {status}  {dim(t.get("expires_at", ""))}')


def _revoke_token(host, session, folder_id, token_id):
    from cli.api.auth import get_csrf
    csrf = get_csrf(host, session)

    res = session.post(
        f'{host}/folders/{folder_id}/share/{token_id}/revoke/',
        headers={'X-CSRFToken': csrf, 'Referer': f'{host}/'},
        timeout=15,
    )
    if res.ok:
        print(f'  ✓ token {token_id} revoked')
    else:
        print(f'  ✗ {res.status_code}: {res.text}')
        sys.exit(1)
