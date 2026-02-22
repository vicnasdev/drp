"""
drp collection — manage drop collections.

  drp collection ls                    list your collections
  drp collection new <name>            create a new collection
  drp collection add <slug> <key>      add a drop to a collection
  drp collection add <slug> -f <key>   add a file drop to a collection
  drp collection rm <slug> <key>       remove a drop from a collection
  drp collection open <slug>           print the collection URL
"""

import json
import sys

import requests

from cli import config
from cli.session import auto_login
from cli.api.helpers import ok, err


def _require_auth(cfg, host, session):
    if not cfg.get('email'):
        err('drp collection requires a logged-in account. Run: drp login')
        sys.exit(1)
    authed = auto_login(cfg, host, session)
    if not authed:
        err('Not logged in. Run: drp login')
        sys.exit(1)


def _fetch_collections(host, session):
    res = session.get(
        f'{host}/auth/account/',
        headers={'Accept': 'application/json'},
        timeout=15,
    )
    res.raise_for_status()
    return res.json().get('collections', [])


def _find_collection_id(host, session, slug):
    """
    Collections don't expose their DB id in the account endpoint,
    so we resolve the slug → id via the detail page JSON.
    Returns collection id or None.
    """
    cfg = config.load()
    username = cfg.get('username', '')
    if not username:
        return None
    res = session.get(
        f'{host}/@{username}/{slug}/',
        headers={'Accept': 'application/json'},
        timeout=10,
        allow_redirects=False,
    )
    if res.ok:
        return res.json().get('id')
    return None


def cmd_collection(args):
    from cli.format import dim, cyan, magenta, green, red, grey, bold

    cfg  = config.load()
    host = cfg.get('host')
    if not host:
        err('Not configured. Run: drp setup')
        sys.exit(1)

    session  = requests.Session()
    sub      = getattr(args, 'col_cmd', None)
    username = cfg.get('username', '')

    # ── ls ────────────────────────────────────────────────────────────────────
    if sub == 'ls' or sub is None:
        _require_auth(cfg, host, session)
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
            prefix     = f'@{username}/' if username else ''
            url        = f'{host}/@{username}/{slug}/' if username else ''
            print(
                f'  {magenta(prefix + slug):<32}  '
                f'{dim(name):<24}  '
                f'{grey(str(drop_count) + " drop" + ("s" if drop_count != 1 else ""))}'
            )
            if url:
                print(f'  {dim("  " + url)}')
        return

    # ── new ───────────────────────────────────────────────────────────────────
    if sub == 'new':
        _require_auth(cfg, host, session)
        name = ' '.join(getattr(args, 'name_parts', []) or [])
        if not name:
            err('Provide a collection name: drp collection new "my notes"')
            sys.exit(1)

        from cli.api.auth import get_csrf
        csrf = get_csrf(host, session)
        try:
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
        _require_auth(cfg, host, session)

        slug    = getattr(args, 'slug', '')
        key     = getattr(args, 'key', '')
        is_file = getattr(args, 'file', False)
        ns      = 'f' if is_file else 'c'

        if not slug or not key:
            err(f'Usage: drp collection {sub} <slug> <key>')
            sys.exit(1)

        # Resolve collection id
        from cli.spinner import Spinner
        from cli.api.auth import get_csrf

        collection_id = None
        try:
            with Spinner('resolving'):
                # Fetch all collections to find the id by slug
                data = session.get(
                    f'{host}/auth/account/',
                    headers={'Accept': 'application/json'},
                    timeout=10,
                ).json()
                # The account endpoint doesn't include ids, so we hit the
                # collection detail page to get one
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

        csrf = get_csrf(host, session)
        action = 'add' if sub == 'add' else 'remove'
        try:
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
        url = f'{host}/@{username}/{slug}/'
        print(url)
        return

    err(f'Unknown subcommand: {sub}. Try: drp collection ls|new|add|rm|open')
    sys.exit(1)
