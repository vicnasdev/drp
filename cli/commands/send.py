"""
drp send / claim — transfer drop ownership via one-time tokens.

  drp send <key>       generate a transfer token (you must own the drop)
  drp send -f <key>    generate token for a file drop
  drp claim <token>    claim a drop sent to you (requires login)
"""

import sys

from cli.commands._context import load_context
from cli.crash_reporter import report_outcome


def cmd_send(args):
    cfg, host, session = load_context()
    ns = 'f' if getattr(args, 'file', False) and not getattr(args, 'clip', False) else 'c'
    prefix = 'f/' if ns == 'f' else ''

    try:
        res = session.post(
            f'{host}/{prefix}{args.key}/send/',
            headers={'Accept': 'application/json'},
            timeout=15,
        )
    except Exception as e:
        print(f'  ✗ Network error: {e}', file=sys.stderr)
        sys.exit(1)

    if not res.ok:
        msg = res.json().get('error', 'Unknown error') if res.headers.get('content-type', '').startswith('application/json') else res.text
        print(f'  ✗ {msg}', file=sys.stderr)
        sys.exit(1)

    data = res.json()
    token = data['token']
    expires = data.get('expires_in', '24h')

    from cli.format import dim, bold
    print(f'  ✓ Transfer token for /{prefix}{args.key}/')
    print()
    print(f'    {bold(token)}')
    print()
    print(f'  {dim(f"Expires in {expires}. Recipient runs:")}')
    print(f'    drp claim {token}')


def cmd_claim(args):
    cfg, host, session = load_context()

    try:
        res = session.post(
            f'{host}/claim/{args.token}/',
            headers={'Accept': 'application/json'},
            timeout=15,
        )
    except Exception as e:
        print(f'  ✗ Network error: {e}', file=sys.stderr)
        sys.exit(1)

    if not res.ok:
        msg = res.json().get('error', 'Unknown error') if res.headers.get('content-type', '').startswith('application/json') else res.text
        print(f'  ✗ {msg}', file=sys.stderr)
        sys.exit(1)

    data = res.json()
    prefix = 'f/' if data.get('ns') == 'f' else ''
    sender = data.get('from', 'someone')

    from cli.format import dim
    print(f'  ✓ Claimed /{prefix}{data["key"]}/ from {sender}')
    print(f'    {dim("You are now the owner.")}')
