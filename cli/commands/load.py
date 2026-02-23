"""
drp load — import a JSON export, bookmarking all drops server-side.

  drp load backup.json

Reads a drp export file and sends it to the server, which creates
SavedDrop entries for the current user. No content is transferred —
just the keys. The importer gets no ownership or edit permissions.
Requires login.
"""

import json
import sys

from cli.commands._context import load_context


def cmd_load(args):
    cfg, host, session = load_context(require_login=True)

    try:
        with open(args.file) as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f'  ✗ File not found: {args.file}')
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f'  ✗ Invalid JSON: {e}')
        sys.exit(1)

    from cli.api.auth import get_csrf
    from cli.spinner import Spinner
    csrf = get_csrf(host, session)
    try:
        with Spinner('importing'):
            res = session.post(
                f'{host}/auth/account/import/',
                json=data,
                headers={'Content-Type': 'application/json', 'X-CSRFToken': csrf},
                timeout=15,
            )
    except Exception as e:
        print(f'  ✗ Request failed: {e}')
        sys.exit(1)

    if not res.ok:
        try:
            msg = res.json().get('error', res.text[:200])
        except Exception:
            msg = res.text[:200]
        print(f'  ✗ Import failed: {msg}')
        sys.exit(1)

    result = res.json()
    imported = result.get('imported', 0)
    skipped  = result.get('skipped', 0)

    print(f'  ✓ Imported {imported} drop(s) as saved.' + (f' {skipped} already saved or skipped.' if skipped else ''))
