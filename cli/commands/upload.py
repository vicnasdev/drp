"""
drp up — upload text or a file.

  drp up "hello"              clipboard from string
  echo "hello" | drp up       clipboard from stdin
  drp up report.pdf           file upload
  drp up https://example.com/api     live API reference (fetched fresh on each get)
  drp up https://example.com/f.pdf --remote  server-side upload (no local download)
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
from cli.prompt import prompt_for_value


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


def _fetch_template(host, session, slug):
    """Fetch a drop template by slug. Returns dict or None."""
    try:
        res = session.get(f'{host}/auth/templates/{slug}/', timeout=10)
        if res.ok:
            return res.json()
    except Exception:
        pass
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
    password   = getattr(args, 'password', None)  # Can be None, '', '__prompt__', or a value
    force_file = getattr(args, 'file', False)
    force_clip = getattr(args, 'clip', False)
    schedule   = getattr(args, 'schedule', None)
    webhook    = getattr(args, 'webhook', None)
    notify     = getattr(args, 'notify', None)
    alias      = getattr(args, 'alias', None)
    template   = getattr(args, 'template', None)
    is_public  = getattr(args, 'public', False)
    tags       = getattr(args, 'tag', None)

    if target is None or target == '-':
        if sys.stdin.isatty():
            # No stdin and no target — check if template provides content
            if template:
                tpl = _fetch_template(host, session, template)
                if not tpl:
                    print(f'  ✗ Template "{template}" not found.')
                    sys.exit(1)
                if tpl.get("content"):
                    target = tpl["content"]
                if tpl.get("burn") and not burn:
                    burn = True
                if tpl.get("expiry_days") and not getattr(args, 'expires', None):
                    args.expires = f'{tpl["expiry_days"]}d'
                if tpl.get("password") and password is None:
                    password = '__prompt__'
                template = None  # already applied
                if target is None:
                    print('  ✗ No input. Provide text, a file path, a URL, or pipe via stdin.')
                    sys.exit(1)
            else:
                print('  ✗ No input. Provide text, a file path, a URL, or pipe via stdin.')
                sys.exit(1)
        else:
            target = sys.stdin.read()

    # Apply template defaults (overridden by explicit flags)
    if template:
        tpl = _fetch_template(host, session, template)
        if tpl:
            if tpl.get("burn") and not burn:
                burn = True
            if tpl.get("expiry_days") and not getattr(args, 'expires', None):
                args.expires = f'{tpl["expiry_days"]}d'
            if tpl.get("password") and password is None:
                password = '__prompt__'
        else:
            print(f'  ✗ Template "{template}" not found.')
            sys.exit(1)

    # Prompt for password if requested but not provided
    if password == '__prompt__':
        password = prompt_for_value('password', '', secret=True, allow_empty=False)
    elif password is None:
        password = ''

    if not force_clip and (target.startswith('http://') or target.startswith('https://')):
        if getattr(args, 'remote', False):
            _upload_url_remote(host, session, target, key, cfg, args, password,
                               schedule=schedule, webhook=webhook, notify=notify,
                               is_public=is_public, tags=tags)
        else:
            _upload_url(host, session, target, key, cfg, args, password,
                        schedule=schedule, webhook=webhook, notify=notify,
                        is_public=is_public, tags=tags)
        return

    elif not force_clip and (force_file or os.path.isfile(target)):
        _upload_file(host, session, target, key, cfg, args, password,
                     schedule=schedule, webhook=webhook, notify=notify,
                     is_public=is_public, tags=tags)
        return

    _upload_text(host, session, target, key, cfg, args, burn=burn, password=password,
                 schedule=schedule, webhook=webhook, notify=notify,
                 is_public=is_public, tags=tags)

    # Create alias after upload if requested
    if alias and key:
        from cli.api.auth import get_csrf
        csrf = get_csrf(host, session)
        import json
        res = session.post(
            f'{host}/auth/aliases/create/',
            json={'alias': alias, 'key': key},
            headers={'X-CSRFToken': csrf, 'Referer': f'{host}/'},
            timeout=15,
        )
        if res.ok:
            from cli.format import dim
            print(f'  {dim("alias created:")} @{cfg.get("username", "?")}/{alias}')


def _upload_url(host, session, url, key, cfg, args, password='',
                schedule=None, webhook=None, notify=None,
                is_public=False, tags=None):
    """Store a URL as a live API reference — drp get will fetch fresh each time."""
    from cli.format import dim
    from cli.spinner import Spinner

    expiry_days = _parse_expires(getattr(args, 'expires', None))
    _test_mode = os.environ.get('DRP_TEST_MODE') == '1'

    with Spinner('uploading'):
        result_key = api.upload_text(
            host, session, url, key=key,
            expiry_days=expiry_days,
            burn=False,
            password=password or None,
            is_test=_test_mode,
            schedule=schedule,
            webhook_url=webhook,
            notify=notify,
            is_public=is_public,
            tags=tags,
            source_url=url,
        )
    if not result_key:
        report_outcome('up', 'upload_text returned None for URL reference')
        sys.exit(1)

    final_url = f'{host}/{result_key}/'
    print(final_url)
    print(f'  {dim("live reference")} → {url}')
    _try_copy(final_url)
    config.record_drop(result_key, 'text', host=host)
    from cli.completion import record_key
    record_key(result_key)


def _upload_url_remote(host, session, url, key, cfg, args, password='',
                       schedule=None, webhook=None, notify=None,
                       is_public=False, tags=None):
    """Server-side URL upload — server fetches the file directly to storage."""
    from cli.format import dim
    from cli.spinner import Spinner

    expiry_days = _parse_expires(getattr(args, 'expires', None))
    _test_mode = os.environ.get('DRP_TEST_MODE') == '1'

    with Spinner('server uploading'):
        result = api.upload_from_url(
            host, session, url, key=key,
            expiry_days=expiry_days,
            password=password or None,
            is_test=_test_mode,
            schedule=schedule,
            webhook_url=webhook,
            notify=notify,
            is_public=is_public,
            tags=tags,
        )
    if not result:
        report_outcome('up', 'upload_from_url returned None')
        sys.exit(1)

    result_key, filename, filesize = result
    final_url = f'{host}/{result_key}/'
    print(final_url)
    size_str = _fmt_size(filesize) if filesize else ''
    desc = f'{dim("remote")} ← {url}'
    if filename:
        desc += f'  {dim(filename)}'
    if size_str:
        desc += f'  {dim(size_str)}'
    print(f'  {desc}')
    _try_copy(final_url)
    config.record_drop(result_key, 'file', filename=filename, host=host)
    from cli.completion import record_key
    record_key(result_key)


def _fmt_size(n: int) -> str:
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1024:
            return f'{n:.0f} {unit}' if unit == 'B' else f'{n:.1f} {unit}'
        n /= 1024
    return f'{n:.1f} TB'


def _upload_file(host, session, path, key, cfg, args, password='',
                 schedule=None, webhook=None, notify=None,
                 is_public=False, tags=None):
    expiry_days = _parse_expires(getattr(args, 'expires', None))
    _test_mode = os.environ.get('DRP_TEST_MODE') == '1'

    # Default key to slugified filename when not explicitly provided
    if not key:
        key = api.slug(os.path.basename(path))

    result_key = api.upload_file(host, session, path, key=key,
                                 expiry_days=expiry_days, password=password or None,
                                 is_test=_test_mode, schedule=schedule,
                                 webhook_url=webhook, notify=notify,
                                 is_public=is_public, tags=tags)
    if not result_key:
        report_outcome('up', 'upload_file returned None (prepare/confirm flow failed)')
        sys.exit(1)

    url = f'{host}/{result_key}/'
    print(url)
    _try_copy(url)
    config.record_drop(result_key, 'file',
                       filename=os.path.basename(path), host=host)
    from cli.completion import record_key
    record_key(result_key)


def _upload_text(host, session, text, key, cfg, args, burn=False, password='',
                 schedule=None, webhook=None, notify=None,
                 is_public=False, tags=None):
    from cli.spinner import Spinner
    expiry_days = _parse_expires(getattr(args, 'expires', None))
    _test_mode = os.environ.get('DRP_TEST_MODE') == '1'

    with Spinner('uploading'):
        result_key = api.upload_text(
            host, session, text, key=key,
            expiry_days=expiry_days,
            burn=burn,
            password=password or None,
            is_test=_test_mode,
            schedule=schedule,
            webhook_url=webhook,
            notify=notify,
            is_public=is_public,
            tags=tags,
        )
    if not result_key:
        report_outcome('up', 'upload_text returned None for clipboard drop')
        sys.exit(1)

    url = f'{host}/{result_key}/'
    print(url)
    _try_copy(url)
    config.record_drop(result_key, 'text', host=host)
    from cli.completion import record_key
    record_key(result_key)


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
