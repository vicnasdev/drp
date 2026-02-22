"""
drp get — fetch a clipboard drop or download a file.

  drp get <key>                  print clipboard to stdout
  drp get <key> --url            print the drop URL without fetching content
  drp get -f <key>               download file (saves to current directory)
  drp get -f <key> -o name       download with custom filename
  drp get -f <key> --url         print the file drop URL without downloading
  drp get <key> --timing         show per-phase timing breakdown
  drp get <key> --password PW    supply password for protected drops
"""

import sys
import getpass

from cli import api
from cli.commands._context import load_context
from cli.timing import Timer


def cmd_get(args):
    t = Timer(enabled=getattr(args, 'timing', False))

    # --url shortcut: no network call needed beyond config
    if getattr(args, 'url', False):
        from cli import config
        cfg = config.load()
        host = cfg.get('host')
        if not host:
            print('  ✗ Not configured. Run: drp setup')
            import sys; sys.exit(1)
        if getattr(args, 'file', False) and not getattr(args, 'clip', False):
            print(f'{host}/f/{args.key}/')
        else:
            print(f'{host}/{args.key}/')
        return

    cfg, host, session = load_context()
    t.instrument(session)
    t.checkpoint('load config')

    password = getattr(args, 'password', None) or ''

    if getattr(args, 'file', False) and not getattr(args, 'clip', False):
        _get_file(args, host, session, t, password)
    else:
        _get_clipboard(args, host, session, t, password)


# ── Clipboard ─────────────────────────────────────────────────────────────────

def _get_clipboard(args, host, session, t, password=''):
    from cli.spinner import Spinner

    with Spinner('fetching'):
        kind, content = api.get_clipboard(host, session, args.key,
                                          timer=t, password=password)

    if kind == 'password_required':
        try:
            password = getpass.getpass(f'  Password for /{args.key}/: ')
        except (KeyboardInterrupt, EOFError):
            print()
            sys.exit(1)
        with Spinner('fetching'):
            kind, content = api.get_clipboard(host, session, args.key,
                                              timer=t, password=password)
        if kind == 'password_required':
            print('  ✗ Wrong password.', file=sys.stderr)
            t.print()
            sys.exit(1)

    if kind == 'text':
        t.print()
        print(content)
        return

    if kind is None and content is None:
        try:
            with Spinner('checking'):
                res = session.get(
                    f'{host}/f/{args.key}/',
                    headers={'Accept': 'application/json'},
                    timeout=10,
                )
            if res.ok and res.json().get('kind') == 'file':
                t.print()
                print(f'  ↳ This is a file drop. Use: drp get -f {args.key}')
                return
        except Exception:
            pass

        t.print()
        sys.exit(1)


# ── File ──────────────────────────────────────────────────────────────────────

def _get_file(args, host, session, t, password=''):
    from cli.spinner import Spinner

    with Spinner('fetching'):
        kind, result = api.get_file(host, session, args.key, password=password)

    if kind == 'password_required':
        try:
            password = getpass.getpass(f'  Password for /f/{args.key}/: ')
        except (KeyboardInterrupt, EOFError):
            print()
            sys.exit(1)
        with Spinner('fetching'):
            kind, result = api.get_file(host, session, args.key, password=password)
        if kind == 'password_required':
            print('  ✗ Wrong password.', file=sys.stderr)
            t.print()
            sys.exit(1)

    if kind != 'file' or result is None:
        t.print()
        sys.exit(1)

    content, filename = result
    output_name = getattr(args, 'output', None) or filename or args.key

    t.checkpoint('download complete')

    try:
        with open(output_name, 'wb') as f:
            f.write(content)
    except OSError as e:
        print(f'  ✗ Could not write {output_name}: {e}', file=sys.stderr)
        t.print()
        sys.exit(1)

    t.print()
    print(f'  ✓ Saved {output_name}')
