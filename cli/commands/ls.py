"""
drp ls — list drops and collections.

  drp ls             list keys (clipboards + files + saved)
  drp ls -l          long format with size, time, expiry (human-readable sizes)
  drp ls -l --bytes  long format with raw byte counts
  drp ls -t c        only clipboards
  drp ls -t f        only files
  drp ls -t s        only saved (bookmarked) drops
  drp ls --col       show collections instead
  drp ls --export    export as JSON (includes saved and collections)
"""

import json
import sys
from datetime import datetime, timezone

import requests

from cli import config
from cli.session import auto_login


# ── Formatting helpers ────────────────────────────────────────────────────────

def _human(n):
    for unit in ('B', 'K', 'M', 'G', 'T'):
        if n < 1024:
            return f'{n:.0f}{unit}' if unit == 'B' else f'{n:.1f}{unit}'
        n /= 1024
    return f'{n:.1f}P'


def _since(iso):
    if not iso:
        return '—'
    try:
        dt = datetime.fromisoformat(iso.replace('Z', '+00:00'))
        diff = datetime.now(timezone.utc) - dt
        s = int(diff.total_seconds())
        if s < 60:      return f'{s}s ago'
        if s < 3600:    return f'{s//60}m ago'
        if s < 86400:   return f'{s//3600}h ago'
        return f'{s//86400}d ago'
    except Exception:
        return iso[:10]


def _until(iso):
    if not iso:
        return 'no expiry'
    try:
        dt = datetime.fromisoformat(iso.replace('Z', '+00:00'))
        diff = dt - datetime.now(timezone.utc)
        s = int(diff.total_seconds())
        if s < 0:        return 'expired'
        if s < 3600:     return f'{s//60}m left'
        if s < 86400:    return f'{s//3600}h left'
        return f'{s//86400}d left'
    except Exception:
        return iso[:10]


# ── Main ──────────────────────────────────────────────────────────────────────

def cmd_ls(args):
    cfg = config.load()
    host = cfg.get('host')
    if not host:
        print('  ✗ Not configured. Run: drp setup')
        sys.exit(1)

    if not cfg.get('email'):
        print('  ✗ drp ls requires a logged-in account. Run: drp login')
        sys.exit(1)

    session = requests.Session()
    authed = auto_login(cfg, host, session)
    if not authed:
        print('  ✗ Not logged in. Run: drp login')
        sys.exit(1)

    from cli.spinner import Spinner
    from cli.format import dim, green, cyan, yellow, magenta, blue, grey, bold

    try:
        with Spinner('loading'):
            res = session.get(
                f'{host}/auth/account/',
                headers={'Accept': 'application/json'},
                timeout=15,
            )
            res.raise_for_status()
            data = res.json()
    except Exception as e:
        print(f'  ✗ Could not fetch drops: {e}')
        sys.exit(1)

    drops       = data.get('drops', [])
    saved       = data.get('saved', [])
    collections = data.get('collections', [])

    # ── Collections mode ──────────────────────────────────────────────────────
    if getattr(args, 'col', False):
        if not collections:
            print(dim('  (no collections)'))
            return
        username = cfg.get('username', '')
        for col in collections:
            slug       = col.get('slug', '')
            name       = col.get('name', slug)
            drop_count = len(col.get('drops', []))
            prefix     = f'@{username}/' if username else ''
            print(f'  {magenta(prefix + slug):<32}  {dim(name)}  {grey(str(drop_count) + " drops")}')
        return

    # ── Filter ────────────────────────────────────────────────────────────────
    ns_filter = getattr(args, 'type', None)
    if ns_filter == 'c':
        drops = [d for d in drops if d['ns'] == 'c']
        saved = []
    elif ns_filter == 'f':
        drops = [d for d in drops if d['ns'] == 'f']
        saved = []
    elif ns_filter == 's':
        drops = []

    # ── Sort ──────────────────────────────────────────────────────────────────
    sort_by = getattr(args, 'sort', None)
    reverse = getattr(args, 'reverse', False)

    if sort_by == 'name':
        drops.sort(key=lambda d: d['key'], reverse=reverse)
    elif sort_by == 'size':
        drops.sort(key=lambda d: d.get('filesize', 0), reverse=not reverse)
    elif sort_by == 'time':
        drops.sort(key=lambda d: d.get('created_at', ''), reverse=not reverse)
    else:
        drops.sort(key=lambda d: d.get('created_at', ''), reverse=True)
        saved.sort(key=lambda s: s.get('saved_at', ''), reverse=True)

    # ── Export ────────────────────────────────────────────────────────────────
    if getattr(args, 'export', False):
        out = {'drops': drops, 'saved': saved, 'collections': collections}
        json.dump(out, sys.stdout, indent=2)
        print()
        return

    long_fmt = getattr(args, 'long', False)
    raw_bytes = getattr(args, 'bytes', False)

    # ── Short format ──────────────────────────────────────────────────────────
    all_empty = not drops and not saved
    if all_empty:
        print(dim('  (no drops)'))
        return

    if not long_fmt:
        for d in drops:
            key_str = cyan(d['key']) if d['ns'] == 'c' else blue('f/' + d['key'])
            lock    = yellow(' 🔒') if d.get('locked') else ''
            print(f'  {key_str}{lock}')
        if drops and saved:
            print()
        for s in saved:
            key_str = cyan(s['key']) if s['ns'] == 'c' else blue('f/' + s['key'])
            print(f'  {key_str}  {dim("[saved]")}')
        return

    # ── Long format ───────────────────────────────────────────────────────────
    def fmt_size(n):
        if n == 0:
            return '—'
        return str(n) if raw_bytes else _human(n)

    rows = []
    for d in drops:
        is_file = d['ns'] == 'f'
        key_col = blue(f'f/{d["key"]}') if is_file else cyan(d['key'])
        size    = fmt_size(d['filesize']) if d['kind'] == 'file' else '—'
        created = _since(d.get('created_at'))
        expires = _until(d.get('expires_at')) if d.get('expires_at') else grey('idle')
        lock    = yellow('🔒') if d.get('locked') else '  '
        rows.append((lock, key_col, d['key'], size, created, expires, ''))

    if drops and saved:
        rows.append(None)  # separator

    for s in saved:
        is_file = s['ns'] == 'f'
        key_col = blue(f'f/{s["key"]}') if is_file else cyan(s['key'])
        saved_at = _since(s.get('saved_at'))
        rows.append(('🔖', key_col, s['key'], '—', saved_at, '—', dim('[saved]')))

    if not rows:
        print(dim('  (no drops)'))
        return

    # Calculate widths from raw key strings (not colour-escaped)
    key_w     = max((len(r[2]) + (2 if r[2] == r[2] else 0) for r in rows if r), default=4)
    size_w    = max((len(r[3]) for r in rows if r), default=4)
    created_w = max((len(r[4]) for r in rows if r), default=7)

    for row in rows:
        if row is None:
            print()
            continue
        lock, key_col, raw_key, size, created, expires, tag = row
        # Pad based on raw key length to keep columns aligned despite ANSI codes
        is_file = raw_key.startswith('f/') or False
        display_len = len(raw_key) + (2 if 'f/' not in raw_key[:2] else 0)
        padding = ' ' * max(0, key_w - len(raw_key))
        print(
            f'  {lock}  {key_col}{padding}  '
            f'{grey(size):>{size_w + 15}}  '
            f'{grey(created):>{created_w + 15}}  '
            f'{dim(expires)}'
            + (f'  {tag}' if tag else '')
        )
