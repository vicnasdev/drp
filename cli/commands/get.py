"""
drp get — fetch a clipboard drop, download a file, or fetch an external URL.

  drp get <key>                  print clipboard to stdout
  drp get <key> --url            print the drop URL without fetching content
  drp get -f <key>               download file (saves to current directory)
  drp get -f <key> -o name       download with custom filename
  drp get -f <key> --url         print the file drop URL without downloading
  drp get <key> --timing         show per-phase timing breakdown
  drp get <key> --password PW    supply password for protected drops
  drp get <key> --parse          auto-detect format and print parsed output
  drp get <key> --field a.b      extract a nested field (dot-separated path)
  drp get <key>.field            shorthand for --field
  drp get https://api.example.com/data  fetch external URL (paid plans)
"""

import sys
import getpass

from cli import api
from cli.commands._context import load_context
from cli.timing import Timer


def cmd_get(args):
    t = Timer(enabled=getattr(args, 'timing', False))

    key = args.key

    # ── External URL fetch (paid feature) ─────────────────────────────────
    if key.startswith('http://') or key.startswith('https://'):
        cfg, host, session = load_context()
        t.instrument(session)
        t.checkpoint('load config')
        _get_url(args, key, host, session, t)
        return

    # ── Dot-access shorthand: "key.field" → key + --field ─────────────────
    field = getattr(args, 'field', None) or ''
    if '.' in key and not field:
        parts = key.split('.', 1)
        key = parts[0]
        field = parts[1]
        args.key = key  # update for downstream

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
        _get_clipboard(args, host, session, t, password, parse=getattr(args, 'parse', False), field=field)


# ── Clipboard ─────────────────────────────────────────────────────────────────

def _get_clipboard(args, host, session, t, password='', parse=False, field=''):
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
        # Smart parse / field extraction
        if parse or field:
            _print_smart(content, field)
        else:
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


# ── Smart parse / field extraction ────────────────────────────────────────────

def _print_smart(content: str, field: str = ''):
    """Parse content, optionally extract a field, and print."""
    from cli.smart_parse import smart_parse, dot_access, format_parsed

    fmt, parsed = smart_parse(content)

    if field:
        if fmt == 'text':
            print(f'  ✗ Cannot extract field from plain text.', file=sys.stderr)
            print(content)
            return
        try:
            value = dot_access(parsed, field)
        except KeyError as e:
            print(f'  ✗ {e}', file=sys.stderr)
            sys.exit(1)
        # Print the extracted value
        if isinstance(value, (dict, list)):
            import json
            print(json.dumps(value, indent=2, ensure_ascii=False))
        else:
            print(value)
        return

    # No field — print full parsed output with format label
    print(f'  [{fmt}]')
    print(format_parsed(fmt, parsed))


# ── URL fetch ─────────────────────────────────────────────────────────────────

def _get_url(args, url, host, session, t):
    """Fetch content from an external URL (paid feature)."""
    from cli.spinner import Spinner

    # Plan gate — URL fetch requires starter+
    try:
        with Spinner('checking plan'):
            res = session.get(
                f'{host}/auth/account/',
                headers={'Accept': 'application/json'},
                timeout=10,
            )
        if res.ok:
            plan = res.json().get('plan', 'free')
            if plan not in ('starter', 'pro'):
                print('  ✗ URL fetch requires a Starter or Pro plan.')
                print('    Upgrade at https://drp.fyi/help/plans/')
                sys.exit(1)
        elif res.status_code in (401, 403):
            print('  ✗ Login required for URL fetch. Run: drp login')
            sys.exit(1)
    except Exception:
        pass  # Network issue — optimistic allow

    t.checkpoint('plan check')

    try:
        with Spinner('fetching URL'):
            r = session.get(url, timeout=30, headers={'User-Agent': 'drp-cli'})
            r.raise_for_status()
            content = r.text
    except Exception as e:
        print(f'  ✗ Failed to fetch URL: {e}', file=sys.stderr)
        t.print()
        sys.exit(1)

    t.checkpoint('fetch URL')
    t.print()

    parse = getattr(args, 'parse', False)
    field = getattr(args, 'field', None) or ''

    if parse or field:
        _print_smart(content, field)
    else:
        # Auto-detect if JSON response
        ct = getattr(r, 'headers', {}).get('content-type', '')
        if 'json' in ct:
            _print_smart(content, field)
        else:
            print(content)
