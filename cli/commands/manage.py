"""
Drop management commands: rm, mv, renew.
"""

import sys

import requests

from cli import config, api
from cli.session import auto_login
from cli.commands._context import load_context
from cli.format import human_time
from cli.crash_reporter import report_outcome


def cmd_rm(args):
    from cli.spinner import Spinner
    cfg, host, session = load_context()
    key = args.key

    with Spinner('deleting'):
        ok = api.delete(host, session, key)

    if ok:
        print(f'  ✓ Deleted /{key}/')
        config.remove_local_drop(key)
    else:
        report_outcome('rm', 'delete returned False')
        print(f'  ✗ Could not delete /{key}/.')
        sys.exit(1)


def cmd_mv(args):
    from cli.spinner import Spinner
    cfg, host, session = load_context()
    key = args.key

    with Spinner('renaming'):
        result = api.rename(host, session, key, args.new_key)

    if isinstance(result, str):
        print(f'  ✓ /{key}/ → /{result}/')
        config.rename_local_drop(key, result)

    elif result is False:
        print(f'  ✗ Could not rename /{key}/.')
        sys.exit(1)

    else:
        report_outcome('mv', 'rename returned None')
        print(f'  ✗ Could not rename /{key}/.')
        sys.exit(1)


def cmd_renew(args):
    from cli.spinner import Spinner
    cfg, host, session = load_context()
    key = args.key

    with Spinner('renewing'):
        expires_at, renewals = api.renew(host, session, key)

    if expires_at:
        print(f'  ✓ /{key}/ renewed → expires {human_time(expires_at)} (renewal #{renewals})')
    else:
        report_outcome('renew', 'renew returned (None, None)')
        print(f'  ✗ Could not renew /{key}/.')
        sys.exit(1)


def cmd_cp(args):
    from cli.spinner import Spinner
    cfg, host, session = load_context()
    key = args.key
    new_key = getattr(args, 'new_key', None)

    with Spinner('copying'):
        result = api.copy_drop(host, session, key, new_key)

    if isinstance(result, str):
        print(f'  ✓ /{key}/ → /{result}/')
        config.record_drop(result, 'text', host=host)
    elif result is False:
        sys.exit(1)
    else:
        report_outcome('cp', 'copy returned None')
        print(f'  ✗ Could not copy /{key}/.')
        sys.exit(1)


def cmd_save(args):
    from cli.spinner import Spinner
    cfg, host, session = load_context(require_login=True)
    key = args.key

    with Spinner('saving'):
        ok = api.save_bookmark(host, session, key)

    if ok:
        print(f'  ✓ Bookmarked /{key}/')
    else:
        print(f'  ✗ Could not bookmark /{key}/.')
        sys.exit(1)


def cmd_lock(args):
    from cli.spinner import Spinner
    from cli.prompt import prompt_for_value
    cfg, host, session = load_context()
    key = args.key
    remove = getattr(args, 'remove', False)
    password = getattr(args, 'password', None)

    if not remove:
        if password == '__prompt__' or password is None:
            password = prompt_for_value('password', '', secret=True, allow_empty=False)
        with Spinner('locking'):
            ok = api.lock_drop(host, session, key, password=password)
        if ok:
            print(f'  ✓ /{key}/ is now password-protected.')
        else:
            print(f'  ✗ Could not set password on /{key}/.')
            sys.exit(1)
    else:
        with Spinner('unlocking'):
            ok = api.lock_drop(host, session, key, remove=True)
        if ok:
            print(f'  ✓ Password removed from /{key}/.')
        else:
            print(f'  ✗ Could not remove password from /{key}/.')
            sys.exit(1)


def cmd_mkdir(args):
    from cli.spinner import Spinner
    cfg, host, session = load_context(require_login=True)
    name = args.name
    parent_slug = getattr(args, 'parent', None)

    parent_id = None
    if parent_slug:
        # Resolve parent folder slug to ID
        username = cfg.get('username', '')
        if username:
            try:
                res = session.get(
                    f'{host}/@{username}/{parent_slug}/',
                    headers={'Accept': 'application/json'},
                    timeout=8,
                )
                if res.ok:
                    parent_id = res.json().get('id')
                else:
                    print(f'  ✗ Parent folder "{parent_slug}" not found.')
                    sys.exit(1)
            except Exception as e:
                print(f'  ✗ {e}')
                sys.exit(1)

    with Spinner('creating folder'):
        result = api.create_folder(host, session, name, parent_id=parent_id)

    if result:
        slug = result.get('slug', name)
        print(f'  ✓ Folder /{slug}/ created.')
    else:
        print(f'  ✗ Could not create folder "{name}".')
        sys.exit(1)