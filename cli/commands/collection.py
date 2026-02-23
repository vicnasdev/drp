"""
drp collection — manage drop collections.

  drp collection ls                    list your collections
  drp collection new <n>            create a new collection
  drp collection add <slug> <key>      add a drop to a collection
  drp collection add <slug> -f <key>   add a file drop to a collection
  drp collection rm <slug> <key>       remove a drop from a collection
  drp collection open <slug>           print the collection URL
"""

import sys

from cli.commands._context import load_context
from cli.api.helpers import ok, err


def _fetch_collections(host, session):
    res = session.get(
        f'{host}/auth/account/',
        headers={'Accept': 'application/json'},
        timeout=15,
    )
    res.raise_for_status()
    return res.json().get('collections', [])


def cmd_collection(args):
    from cli.format import dim, cyan, magenta, green, red, grey, bold

    cfg, host, session = load_context(require_login=True)

    sub      = getattr(args, 'col_cmd', None)
    username = cfg.get('username', '')

    # ── ls ────────────────────────────────────────────────────────────────────
    if sub == 'ls' or sub is None:
        from cli.spinner import Spinner
        try:
            with Spinner('loading'):
                cols = _fetch_collections(host, session)
        except Exception as e:
            err(f'Could not fetch collections: {e}')
            sys.exit(1)

        if not cols:
            print(dim('  (no collections)'))
            return

        for col in cols:
            slug       = col.get('slug', '')
            name       = col.get('name', slug)
            drop_count = len(col.get('drops', []))
            url        = f'{host}/@{username}/{slug}/' if username else ''
            print(
                f'  {magenta("@" + username + "/" + slug):<32}  '
                f'{dim(name):<24}  '
                f'{grey(str(drop_count) + " drop" + ("s" if drop_count != 1 else ""))}'
            )
            if url:
                print(f'  {dim("  " + url)}')
        return

    # ── new ───────────────────────────────────────────────────────────────────
    if sub == 'new':
        name = ' '.join(getattr(args, 'name_parts', []) or [])
        if not name:
            err('Provide a collection name: drp collection new "my notes"')
            sys.exit(1)

        from cli.api.auth import get_csrf
        csrf = get_csrf(host, session)
        from cli.spinner import Spinner
        try:
            with Spinner('creating'):
                res = session.post(
                    f'{host}/collections/create/',
                    json={'name': name},
                    headers={'X-CSRFToken': csrf, 'Content-Type': 'application/json'},
                    timeout=10,
                )
        except Exception as e:
            err(f'Network error: {e}')
            sys.exit(1)

        if res.status_code == 201:
            data = res.json()
            slug = data.get('slug', '')
            url  = f'{host}/@{username}/{slug}/' if username else data.get('url', '')
            ok(f'{magenta(slug)}  created')
            print(f'  {dim(url)}')
        elif res.status_code == 403:
            err(res.json().get('error', 'Permission denied. Collections require a paid plan.'))
            sys.exit(1)
        else:
            try:
                err(res.json().get('error', f'Server returned {res.status_code}.'))
            except Exception:
                err(f'Server returned {res.status_code}.')
            sys.exit(1)
        return

    # ── add / rm ──────────────────────────────────────────────────────────────
    if sub in ('add', 'rm'):
        slug    = getattr(args, 'slug', '')
        key     = getattr(args, 'key', '')
        ns      = 'f' if getattr(args, 'file', False) else 'c'

        if not slug or not key:
            err(f'Usage: drp collection {sub} <slug> <key>')
            sys.exit(1)

        from cli.spinner import Spinner
        from cli.api.auth import get_csrf

        collection_id = None
        try:
            with Spinner('resolving'):
                if username:
                    detail = session.get(
                        f'{host}/@{username}/{slug}/',
                        headers={'Accept': 'application/json'},
                        timeout=10,
                    )
                    if detail.ok:
                        collection_id = detail.json().get('id')
        except Exception as e:
            err(f'Could not resolve collection: {e}')
            sys.exit(1)

        if not collection_id:
            err(f'Collection "{slug}" not found.')
            sys.exit(1)

        csrf   = get_csrf(host, session)
        action = 'add' if sub == 'add' else 'remove'
        try:
            with Spinner('updating'):
                res = session.post(
                    f'{host}/collections/{collection_id}/{action}/',
                    json={'ns': ns, 'key': key},
                    headers={'X-CSRFToken': csrf, 'Content-Type': 'application/json'},
                    timeout=10,
                )
        except Exception as e:
            err(f'Network error: {e}')
            sys.exit(1)

        if res.ok:
            ns_prefix = 'f/' if ns == 'f' else ''
            if sub == 'add':
                ok(f'{ns_prefix}{key}  →  {magenta(slug)}')
            else:
                ok(f'{ns_prefix}{key}  removed from  {magenta(slug)}')
        else:
            try:
                err(res.json().get('error', f'Server returned {res.status_code}.'))
            except Exception:
                err(f'Server returned {res.status_code}.')
            sys.exit(1)
        return

    # ── open ──────────────────────────────────────────────────────────────────
    if sub == 'open':
        slug = getattr(args, 'slug', '')
        if not slug:
            err('Usage: drp collection open <slug>')
            sys.exit(1)
        if not username:
            err('Username not set. Run: drp login')
            sys.exit(1)
        print(f'{host}/@{username}/{slug}/')
        return

    err(f'Unknown subcommand: {sub}. Try: drp collection ls|new|add|rm|open')
    sys.exit(1)
