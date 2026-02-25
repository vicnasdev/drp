"""
drp save — bookmark a drop to your account.

  drp save key        bookmark a clipboard drop
  drp save -f key     bookmark a file drop

Saving grants no ownership or edit rights — the drop appears
in drp ls under [saved] and in your account dashboard.
Requires login.
"""

import sys

from cli import api
from cli.commands._context import load_context
from cli.commands.manage import _parse_key


def cmd_save(args):
    from cli.spinner import Spinner
    cfg, host, session = load_context(require_login=True)

    ns, key = _parse_key(args.key, args.file, getattr(args, 'clip', False))
    prefix = 'f/' if ns == 'f' else ''

    with Spinner('saving'):
        ok = api.save_bookmark(host, session, key, ns=ns)

    if ok:
        print(f'  ✓ Saved /{prefix}{key}/ — appears in drp ls')
    else:
        sys.exit(1)
