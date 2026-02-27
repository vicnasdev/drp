"""
drp get — fetch a drop, download a file, or fetch an external URL.

  drp get <key>                  print text to stdout / download file
  drp get <key> --url            print the drop URL without fetching content
  drp get <key> -o name          download with custom filename
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

    parse = getattr(args, 'parse', False)
    _get_drop(args, host, session, t, password, parse=parse, field=field)


# ── Drop fetch ────────────────────────────────────────────────────────────────

def _get_drop(args, host, session, t, password='', parse=False, field=''):
    """Fetch a drop — auto-detects text vs file from server response."""
    from cli.spinner import Spinner

    # First try the unified endpoint
    with Spinner('fetching'):
        res = session.get(
            f'{host}/{args.key}/',
            headers=_headers(password),
            timeout=30,
        )

    if res.status_code == 401:
        try:
            password = getpass.getpass(f'  Password for /{args.key}/: ')
        except (KeyboardInterrupt, EOFError):
            print()
            sys.exit(1)
        with Spinner('fetching'):
            res = session.get(
                f'{host}/{args.key}/',
                headers=_headers(password),
                timeout=30,
            )
        if res.status_code == 401:
            print('  ✗ Wrong password.', file=sys.stderr)
            t.print()
            sys.exit(1)

    if not res.ok:
        t.print()
        if res.status_code == 404:
            print(f'  ✗ Drop /{args.key}/ not found.', file=sys.stderr)
        elif res.status_code == 410:
            print(f'  ✗ Drop /{args.key}/ has expired.', file=sys.stderr)
        else:
            print(f'  ✗ Server returned {res.status_code}.', file=sys.stderr)
        sys.exit(1)

    data = res.json()
    kind = data.get('kind')

    if kind == 'file':
        _handle_file_download(args, host, session, data, t, password, parse=parse, field=field)
    elif kind == 'text':
        t.print()
        content = data.get('content', '')

        # Handle special text sub-types
        if data.get('source_url') and data.get('content_type', '').startswith(('image/', 'application/')):
            # Binary live reference
            url = data.get('source_url', '')
            ct  = data.get('content_type', 'binary')
            sz  = data.get('content_length')
            print(f'  ↳ Live reference points to binary content ({ct})')
            if sz:
                print(f'    Size: {sz:,} bytes')
            print(f'    URL:  {url}')
            print(f'  Tip: download directly with  curl -Lo file "{url}"')
            print(f'       or re-upload with        drp up "{url}" --remote')
            return
        if data.get('fetch_error'):
            url  = data.get('source_url', '?')
            err_msg = data.get('fetch_error', 'unknown error')
            print(f'  ✗ Live reference fetch failed', file=sys.stderr)
            print(f'    URL:   {url}', file=sys.stderr)
            print(f'    Error: {err_msg}', file=sys.stderr)
            sys.exit(1)

        if parse or field:
            _print_smart(content, field)
        else:
            print(content)
    else:
        t.print()
        print(f'  ✗ Unknown drop kind: {kind}', file=sys.stderr)
        sys.exit(1)


def _headers(password=''):
    h = {'Accept': 'application/json'}
    if password:
        h['X-Drop-Password'] = password
    return h


def _handle_file_download(args, host, session, data, t, password='', parse=False, field=''):
    """Download a file drop given the JSON metadata from the server."""
    from cli.progress import ProgressBar
    import requests as _requests

    key = args.key
    filename = data.get('filename', key)
    filesize = data.get('filesize', 0)
    b2_url = data.get('presigned_url')

    if not b2_url:
        download_path = data.get('download')
        if not download_path:
            t.print()
            print(f'  ✗ No download URL for /{key}/.', file=sys.stderr)
            sys.exit(1)
        dl_res = session.get(
            f'{host}{download_path}',
            timeout=10,
            allow_redirects=False,
        )
        if dl_res.status_code == 401:
            t.print()
            print('  ✗ Password required.', file=sys.stderr)
            sys.exit(1)
        if dl_res.status_code in (301, 302, 303, 307, 308):
            b2_url = dl_res.headers['Location']
        elif dl_res.ok:
            content = dl_res.content
            if parse or field:
                try:
                    text = content.decode('utf-8')
                except (UnicodeDecodeError, AttributeError):
                    t.print()
                    print('  ✗ File is binary — --parse only works on text-based files.', file=sys.stderr)
                    sys.exit(1)
                t.print()
                _print_smart(text, field, filename=filename or '')
                return
            output_name = getattr(args, 'output', None) or filename or key
            t.checkpoint('download complete')
            with open(output_name, 'wb') as f:
                f.write(content)
            t.print()
            print(f'  ✓ Saved {output_name}')
            return
        else:
            t.print()
            print(f'  ✗ Download redirect failed (HTTP {dl_res.status_code}).', file=sys.stderr)
            sys.exit(1)

    # Stream from B2
    bar = ProgressBar(max(filesize, 1), label='downloading')
    chunks = []
    downloaded = 0
    retries = 3
    CHUNK = 256 * 1024

    for attempt in range(retries + 1):
        req_headers = {}
        if downloaded:
            req_headers['Range'] = f'bytes={downloaded}-'
        try:
            with _requests.get(b2_url, stream=True, timeout=30,
                               headers=req_headers) as stream:
                if stream.status_code not in (200, 206):
                    t.print()
                    print(f'  ✗ B2 download failed (HTTP {stream.status_code}).', file=sys.stderr)
                    sys.exit(1)
                for chunk in stream.iter_content(chunk_size=CHUNK):
                    if chunk:
                        chunks.append(chunk)
                        downloaded += len(chunk)
                        bar.update(len(chunk))
            break
        except (_requests.exceptions.ChunkedEncodingError,
                _requests.exceptions.ConnectionError) as exc:
            if attempt < retries:
                import time as _time
                _time.sleep(1)
                continue
            t.print()
            print(f'  ✗ Download failed after {retries + 1} attempts: {exc}', file=sys.stderr)
            sys.exit(1)

    bar.done()
    content = b''.join(chunks)

    if parse or field:
        try:
            text = content.decode('utf-8')
        except (UnicodeDecodeError, AttributeError):
            t.print()
            print('  ✗ File is binary — --parse only works on text-based files.', file=sys.stderr)
            sys.exit(1)
        t.print()
        _print_smart(text, field, filename=filename or '')
        return

    output_name = getattr(args, 'output', None) or filename or key
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

def _print_smart(content: str, field: str = '', filename: str = ''):
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
    label = fmt
    if fmt == 'text':
        from cli.smart_parse import detect_code_language
        lang = detect_code_language(content, filename)
        if lang:
            label = lang
    print(f'  [{label}]')
    print(format_parsed(fmt, parsed, filename=filename))


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
                         headers={'User-Agent': 'drp'},
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
