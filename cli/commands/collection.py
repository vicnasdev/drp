"""
drp collection — manage drop collections.

  drp collection ls                         list your collections
  drp collection new <name>                 create a new collection
  drp collection new <name> --parent <slug> create a sub-collection
  drp collection add <path> <key>           add a drop to a collection
  drp collection add <path> -f <key>        add a file drop to a collection
  drp collection rm <path> <key>            remove a drop from a collection
  drp collection open <path>                print the collection URL

  <path> can be a slug ("notes") or a nested path ("notes/work").
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

        # Build tree: group by parent_id
        children_map = {}
        roots = []
        for c in cols:
            pid = c.get('parent_id')
            if pid:
                children_map.setdefault(pid, []).append(c)
            else:
                roots.append(c)

        def _print_tree(col, indent=0):
            path       = col.get('path', col.get('slug', ''))
            name       = col.get('name', path)
            drop_count = len(col.get('drops', []))
            prefix     = '  ' + '  ' * indent
            slug_disp  = magenta('@' + username + '/' + path) if indent == 0 else magenta(col.get('slug', ''))
            child_list = children_map.get(col.get('id'), [])
            child_hint = f'  {grey("+" + str(len(child_list)) + " sub")}' if child_list else ''
            print(
                f'{prefix}{slug_disp}  '
                f'{dim(name):<24}  '
                f'{grey(str(drop_count) + " drop" + ("s" if drop_count != 1 else ""))}'
                f'{child_hint}'
            )
            for child in child_list:
                _print_tree(child, indent + 1)

        for root in roots:
            _print_tree(root)
        return

    # ── new ───────────────────────────────────────────────────────────────────
    if sub == 'new':
        name = ' '.join(getattr(args, 'name_parts', []) or [])
        if not name:
            err('Provide a collection name: drp collection new "my notes"')
            sys.exit(1)

        parent_slug = getattr(args, 'parent', None)

        from cli.api.auth import get_csrf
        csrf = get_csrf(host, session)
        from cli.spinner import Spinner

        # Resolve parent collection if --parent is specified
        payload = {'name': name}
        if parent_slug and username:
            try:
                with Spinner('resolving parent'):
                    detail = session.get(
                        f'{host}/@{username}/{parent_slug}/',
                        headers={'Accept': 'application/json'},
                        timeout=10,
                    )
                    if not detail.ok:
                        err(f'Parent collection "{parent_slug}" not found.')
                        sys.exit(1)
                    payload['parent_id'] = detail.json().get('id')
            except SystemExit:
                raise
            except Exception as e:
                err(f'Could not resolve parent: {e}')
                sys.exit(1)

        try:
            with Spinner('creating'):
                res = session.post(
                    f'{host}/collections/create/',
                    json=payload,
                    headers={'X-CSRFToken': csrf, 'Content-Type': 'application/json'},
                    timeout=10,
                )
        except Exception as e:
            err(f'Network error: {e}')
            sys.exit(1)

        if res.status_code == 201:
            data = res.json()
            path = data.get('path', data.get('slug', ''))
            url  = f'{host}/@{username}/{path}/' if username else data.get('url', '')
            ok(f'{magenta(path)}  created')
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
            err('Usage: drp collection open <path>')
            sys.exit(1)
        if not username:
            err('Username not set. Run: drp login')
            sys.exit(1)
        print(f'{host}/@{username}/{slug}/')
        return

    err(f'Unknown subcommand: {sub}. Try: drp collection ls|new|add|rm|open')
    sys.exit(1)
