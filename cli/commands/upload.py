"""
drp up — upload text or a file.

  drp up "hello"              clipboard from string
  echo "hello" | drp up       clipboard from stdin
  drp up report.pdf           file upload
  drp up https://example.com/file.pdf   fetch URL and re-host
  drp up report.pdf --expires 7d
  drp up "secret" --burn      delete after first view
  drp up "secret" --password pw  password-protect (paid accounts only)
"""

import os
import sys

import requests

from cli import config, api
from cli.commands._context import load_context
from cli.crash_reporter import report_outcome


def _parse_expires(value: str) -> int | None:
    if not value:
        return None
    value = value.strip().lower()
    try:
        if value.endswith('y'):
            return int(value[:-1]) * 365
        if value.endswith('d'):
            return int(value[:-1])
        return int(value)
    except ValueError:
        return None


def _copy_to_clipboard(text: str) -> bool:
    if not sys.stdout.isatty():
        return False
    try:
        import pyperclip
        pyperclip.copy(text)
        return True
    except Exception:
        pass
    import subprocess, shutil
    for cmd in (['pbcopy'], ['xclip', '-selection', 'clipboard'],
                ['xsel', '--clipboard', '--input'], ['wl-copy']):
        if shutil.which(cmd[0]):
            try:
                proc = subprocess.run(cmd, input=text.encode(), timeout=3)
                return proc.returncode == 0
            except Exception:
                continue
    return False


def cmd_up(args):
    cfg, host, session = load_context()

    target     = getattr(args, 'target', None)
    key        = args.key
    burn       = getattr(args, 'burn', False)
    password   = getattr(args, 'password', None) or ''
    force_file = getattr(args, 'file', False)
    force_clip = getattr(args, 'clip', False)

    if target is None or target == '-':
        if sys.stdin.isatty():
            print('  ✗ No input. Provide text, a file path, a URL, or pipe via stdin.')
            sys.exit(1)
        target = sys.stdin.read()

    elif not force_clip and (target.startswith('http://') or target.startswith('https://')):
        _upload_url(host, session, target, key, cfg, args, password)
        return

    elif not force_clip and (force_file or os.path.isfile(target)):
        _upload_file(host, session, target, key, cfg, args, password)
        return

    _upload_text(host, session, target, key, cfg, args, burn=burn, password=password)


def _upload_url(host, session, url, key, cfg, args, password=''):
    from cli.progress import ProgressBar
    from cli.format import dim
    import mimetypes, tempfile

    print(f'  {dim("fetching")} {url}')

    try:
        r = requests.get(url, stream=True, timeout=30)
        r.raise_for_status()
    except Exception as e:
        print(f'  ✗ Could not fetch URL: {e}')
        sys.exit(1)

    filename = _filename_from_response(r, url)
    total    = int(r.headers.get('Content-Length', 0))

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(filename)[1])
    bar = ProgressBar(max(total, 1), label='downloading')
    try:
        for chunk in r.iter_content(chunk_size=256 * 1024):
            if chunk:
                tmp.write(chunk)
                bar.update(len(chunk))
        bar.done()
        tmp.flush()
        tmp_path = tmp.name
    finally:
        tmp.close()

    if not key:
        key = api.slug(filename)

    expiry_days = _parse_expires(getattr(args, 'expires', None))

    try:
        result_key = api.upload_file(host, session, tmp_path, key=key,
                                     expiry_days=expiry_days, password=password or None)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    if not result_key:
        report_outcome('up', 'upload_file returned None for URL fetch')
        sys.exit(1)

    final_url = f'{host}/f/{result_key}/'
    print(final_url)
    _try_copy(final_url)
    config.record_drop(result_key, 'file', ns='f', filename=filename, host=host)


def _upload_file(host, session, path, key, cfg, args, password=''):
    if not key:
        key = api.slug(os.path.basename(path))

    expiry_days = _parse_expires(getattr(args, 'expires', None))

    result_key = api.upload_file(host, session, path, key=key,
                                 expiry_days=expiry_days, password=password or None)
    if not result_key:
        report_outcome('up', 'upload_file returned None (prepare/confirm flow failed)')
        sys.exit(1)

    url = f'{host}/f/{result_key}/'
    print(url)
    _try_copy(url)
    config.record_drop(result_key, 'file', ns='f',
                       filename=os.path.basename(path), host=host)


def _upload_text(host, session, text, key, cfg, args, burn=False, password=''):
    expiry_days = _parse_expires(getattr(args, 'expires', None))

    result_key = api.upload_text(
        host, session, text, key=key,
        expiry_days=expiry_days,
        burn=burn,
        password=password or None,
    )
    if not result_key:
        report_outcome('up', 'upload_text returned None for clipboard drop')
        sys.exit(1)

    url = f'{host}/{result_key}/'
    print(url)
    _try_copy(url)
    config.record_drop(result_key, 'text', ns='c', host=host)


def _try_copy(url: str) -> None:
    from cli.format import dim
    if _copy_to_clipboard(url):
        print(f'  {dim("copied to clipboard")}')


def _filename_from_response(r, url: str) -> str:
    cd = r.headers.get('Content-Disposition', '')
    if 'filename=' in cd:
        for part in cd.split(';'):
            part = part.strip()
            if part.startswith('filename='):
                return part[9:].strip('"\'')
    from urllib.parse import urlparse
    path = urlparse(url).path
    if path.endswith('/'):
        return 'download'
    name = os.path.basename(path)
    return name if name else 'download'
