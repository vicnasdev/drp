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
  drp get https://api.example.com/data  fetch external URL
"""

import sys
import getpass

from cli import api
from cli.commands._context import load_context
from cli.timing import Timer
from cli.prompt import prompt_for_value


def cmd_get(args):
    t = Timer(enabled=getattr(args, 'timing', False))

    key = args.key

    # ── External URL fetch ─────────────────────────────────────────────────
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

    password = getattr(args, 'password', None)  # Can be None, '', '__prompt__', or a value
    
    # Prompt for password if requested but not provided
    if password == '__prompt__':
        password = prompt_for_value('password', '', secret=True, allow_empty=False)
    elif password is None:
        password = ''

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
            # Check if it's a live reference (source_url)
            # The API returns source_url when the drop is a live ref
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

def _filename_from_url(r, url: str) -> str:
    """Infer filename from Content-Disposition header or URL path."""
    cd = r.headers.get('Content-Disposition', '')
    if 'filename=' in cd:
        for part in cd.split(';'):
            part = part.strip()
            if part.startswith('filename='):
                return part[9:].strip('"\'')
    from urllib.parse import urlparse
    path = urlparse(url).path.rstrip('/')
    import os
    name = os.path.basename(path)
    return name if name else 'download'


def _is_binary_content(content_type: str) -> bool:
    """Heuristic: is this content-type likely binary data (not text)?"""
    ct = content_type.lower().split(';')[0].strip()
    if ct.startswith('text/'):
        return False
    if ct in ('application/json', 'application/xml', 'application/javascript',
              'application/x-yaml', 'application/yaml', 'application/toml',
              'application/ld+json', 'application/graphql',
              'application/x-www-form-urlencoded'):
        return False
    if '+json' in ct or '+xml' in ct:
        return False
    return True


def _get_url(args, url, host, session, t):
    """Fetch content from an external URL.

    Text responses (JSON, HTML, plain text) are printed to stdout.
    Binary responses (PDFs, images, archives) are saved to a file, with a
    progress bar if the size is known.

    Use-cases:
      drp get https://api.example.com/data           → print JSON
      drp get https://api.example.com/data --parse    → parsed output
      drp get https://api.example.com/data.name       → dot-access field
      drp get https://example.com/report.pdf           → save report.pdf
      drp get https://example.com/report.pdf -o r.pdf  → save as r.pdf
    """
    from cli.spinner import Spinner
    from cli.progress import ProgressBar
    import requests as _req

    t.checkpoint('plan check')

    # ── Streaming download with redirect support ─────────────────────────
    try:
        with Spinner('connecting'):
            r = _req.get(url, stream=True, timeout=30,
                         headers={'User-Agent': 'drp-cli'},
                         allow_redirects=True)
            r.raise_for_status()
    except Exception as e:
        print(f'  ✗ Failed to fetch URL: {e}', file=sys.stderr)
        t.print()
        sys.exit(1)

    content_type = r.headers.get('content-type', '')
    is_binary = _is_binary_content(content_type)
    content_length = int(r.headers.get('content-length', 0))

    parse = getattr(args, 'parse', False)
    field = getattr(args, 'field', None) or ''
    output = getattr(args, 'output', None)

    # ── Binary file → save to disk ───────────────────────────────────────
    if is_binary or output:
        filename = output or _filename_from_url(r, url)
        chunk_size = 256 * 1024
        if content_length:
            bar = ProgressBar(content_length, label='downloading')
        else:
            bar = None

        try:
            with open(filename, 'wb') as f:
                for chunk in r.iter_content(chunk_size=chunk_size):
                    if chunk:
                        f.write(chunk)
                        if bar:
                            bar.update(len(chunk))
        except OSError as e:
            print(f'  ✗ Could not write {filename}: {e}', file=sys.stderr)
            t.print()
            sys.exit(1)
        finally:
            r.close()

        if bar:
            bar.done()

        t.checkpoint('download complete')
        t.print()
        print(f'  ✓ Saved {filename}')
        return

    # ── Text content → stream into memory, print to stdout ───────────────
    try:
        content = r.text
    finally:
        r.close()

    t.checkpoint('fetch URL')
    t.print()

    if parse or field:
        _print_smart(content, field)
    else:
        # Auto-detect if JSON response
        if 'json' in content_type:
            _print_smart(content, field)
        else:
            print(content)
