"""
drp status and drp ping commands.

  drp status           show config, session, local drop count
  drp status <key>     show view count and last viewed for a drop
  drp ping             check server reachability
"""

import sys
import requests

from cli import config
from cli.session import SESSION_FILE
from cli.commands._context import load_context


def cmd_status(args):
    key = getattr(args, 'key', None)
    if key:
        _drop_status(args, key)
        return

    from cli.format import dim, green, bold, cyan
    from cli.spinner import Spinner

    cfg = config.load()

    with Spinner('loading'):
        _sync_local_cache(cfg)

    current_host = cfg.get('host', '')
    local_count  = sum(
        1 for d in config.load_local_drops()
        if d.get('host', '') != current_host or d.get('from_server', False)
    )

    server_count   = None
    local_only     = None
    session_active = SESSION_FILE.exists()
    if session_active:
        try:
            import requests as req_lib
            from cli.session import load_session
            s = req_lib.Session()
            load_session(s)
            res = s.get(
                f'{cfg.get("host", "")}/auth/account/',
                headers={'Accept': 'application/json'},
                timeout=6,
            )
            if res.ok:
                data        = res.json()
                server_keys = {(d.get('ns'), d.get('key')) for d in data.get('drops', [])}
                server_count = len(server_keys)
                local_drops  = config.load_local_drops()
                local_only   = sum(
                    1 for d in local_drops
                    if (d.get('ns'), d.get('key')) not in server_keys
                )
        except Exception:
            pass

    print(bold('drp status'))
    print(dim('──────────'))
    print(f'  {dim("Host:")}        {cfg.get("host", "(not set)")}')

    username    = cfg.get('username', '')
    email       = cfg.get('email', 'anonymous')
    account_str = f'{cyan("@" + username)}  {dim(email)}' if username else dim(email)
    print(f'  {dim("Account:")}     {account_str}')

    session_str = green('active') if session_active else dim('none')
    print(f'  {dim("Session:")}     {session_str}')

    if server_count is not None:
        local_only_str = f'  {dim("(" + str(local_only) + " local-only)")}' if local_only else ''
        print(f'  {dim("Server drops:")} {server_count}{local_only_str}')
        print(f'  {dim("Local cache:")} {local_count}')
    else:
        print(f'  {dim("Local drops:")} {local_count}')

    print(f'  {dim("Config:")}      {config.CONFIG_FILE}')
    print(f'  {dim("Cache:")}       {config.DROPS_FILE}')


def _drop_status(args, key):
    cfg, host, session = load_context()

    ns  = 'f' if getattr(args, 'file', False) and not getattr(args, 'clip', False) else 'c'
    url = f'{host}/f/{key}/' if ns == 'f' else f'{host}/{key}/'

    from cli.spinner import Spinner
    from cli.format import dim, green, bold
    from cli.api.helpers import err

    try:
        with Spinner('fetching'):
            res = session.get(url, headers={'Accept': 'application/json'}, timeout=10)
    except Exception as e:
        err(f'Could not reach server: {e}')
        sys.exit(1)

    if res.status_code == 404:
        err(f'Drop /{key}/ not found.')
        sys.exit(1)
    if res.status_code == 410:
        err(f'Drop /{key}/ has expired.')
        sys.exit(1)
    if not res.ok:
        err(f'Server returned {res.status_code}.')
        sys.exit(1)

    data   = res.json()
    from cli.format import human_time
    prefix = 'f/' if ns == 'f' else ''
    views  = data.get('view_count', 0)
    last   = data.get('last_viewed_at')

    sep = dim('─' * (len(key) + len(prefix) + 3))
    print(f'  {bold("/" + prefix + key + "/")}')
    print(f'  {sep}')
    print(f'  {dim("kind")}        {data.get("kind", "?")}')
    if data.get("filename"):
        print(f'  {dim("file")}        {data["filename"]}')
    print(f'  {dim("views")}       {green(str(views)) if views else dim("0")}')
    print(f'  {dim("last seen")}   {human_time(last) if last else dim("never")}')
    print(f'  {dim("created")}     {human_time(data.get("created_at"))}')
    if data.get('expires_at'):
        print(f'  {dim("expires")}     {human_time(data.get("expires_at"))}')
    else:
        print(f'  {dim("expires")}     {dim("activity-based")}')
    if data.get('burn'):
        from cli.format import red
        print(f'  {dim("burn")}        {red("yes — deletes after first view")}')
    if data.get('password_protected'):
        print(f'  {dim("password")}    yes')
    if data.get('is_public'):
        print(f'  {dim("public")}      yes')
    if data.get('tags'):
        print(f'  {dim("tags")}        {data["tags"]}')


def _sync_local_cache(cfg) -> None:
    try:
        from cli.session import SESSION_FILE
        if not SESSION_FILE.exists():
            return
        email = cfg.get('email')
        host  = cfg.get('host')
        if not email or not host:
            return
        from cli.completion import _do_refresh
        _do_refresh(config, SESSION_FILE)
    except Exception:
        pass


def cmd_ping(args):
    from cli import config as cfg_mod
    from cli.format import green, red
    cfg  = cfg_mod.load()
    host = cfg.get('host')
    if not host:
        print('  ✗ Not configured. Run: drp setup')
        sys.exit(1)

    from cli.spinner import Spinner
    try:
        with Spinner('pinging'):
            res  = requests.get(f'{host}/', timeout=5)
        tick = green('✓')
        print(f'  {tick} {host} reachable (HTTP {res.status_code})')
    except requests.ConnectionError:
        print(f'  {red("✗")} {host} unreachable — connection refused.')
        sys.exit(1)
    except requests.Timeout:
        print(f'  {red("✗")} {host} unreachable — timed out.')
        sys.exit(1)
    except Exception as e:
        print(f'  {red("✗")} {host} unreachable: {e}')
        sys.exit(1)
