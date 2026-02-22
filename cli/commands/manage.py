"""
Drop management commands: rm, mv, renew.

Key format accepted by all commands:
  key       → clipboard (ns=c)
  -f key    → file (ns=f)
"""

import sys

import requests

from cli import config, api
from cli.session import auto_login
from cli.commands._context import load_context
from cli.format import human_time
from cli.crash_reporter import report_outcome


def _parse_key(raw, is_file=False, is_clip=False):
    """Return (ns, key). -f → file ns, -c → clipboard ns, default → clipboard."""
    return ('f', raw) if is_file and not is_clip else ('c', raw)


def cmd_rm(args):
    cfg, host, session = load_context()
    ns, key = _parse_key(args.key, args.file, getattr(args, 'clip', False))

    if api.delete(host, session, key, ns=ns):
        prefix = 'f/' if ns == 'f' else ''
        print(f'  ✓ Deleted /{prefix}{key}/')
        config.remove_local_drop(key)
    else:
        # api.delete() already printed an error and filed an HTTP report for
        # known failures (e.g. 404 wrong namespace). report_outcome() covers
        # the case where it returned False for a non-HTTP reason (e.g. a network
        # exception that was swallowed).
        report_outcome('rm', f'delete returned False for ns={ns} drop')
        print(f'  ✗ Could not delete /{key}/.')
        sys.exit(1)


def cmd_mv(args):
    cfg, host, session = load_context()
    ns, key = _parse_key(args.key, args.file, getattr(args, 'clip', False))
    result = api.rename(host, session, key, args.new_key, ns=ns)

    if isinstance(result, str):
        # Success — result is the confirmed new key from the server
        prefix = 'f/' if ns == 'f' else ''
        print(f'  ✓ /{prefix}{key}/ → /{prefix}{result}/')
        config.rename_local_drop(key, result)

    elif result is False:
        # Known error — api.rename() already printed a message and filed an
        # HTTP report. Don't file a redundant SilentFailure on top of it.
        print(f'  ✗ Could not rename /{key}/.')
        sys.exit(1)

    else:
        # result is None — unexpected failure (network error, unhandled status).
        # api.rename() has already printed what it knows; file a SilentFailure
        # so we have a record that something unexpected happened.
        report_outcome('mv', f'rename returned None for ns={ns} drop')
        print(f'  ✗ Could not rename /{key}/.')
        sys.exit(1)


def cmd_renew(args):
    cfg, host, session = load_context()
    ns, key = _parse_key(args.key, args.file, getattr(args, 'clip', False))
    expires_at, renewals = api.renew(host, session, key, ns=ns)

    if expires_at:
        prefix = 'f/' if ns == 'f' else ''
        print(f'  ✓ /{prefix}{key}/ renewed → expires {human_time(expires_at)} (renewal #{renewals})')
    else:
        report_outcome('renew', f'renew returned (None, None) for ns={ns} drop')
        print(f'  ✗ Could not renew /{key}/.')
        sys.exit(1)