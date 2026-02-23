"""
drp shell — interactive REPL.

Commands available inside the shell:

  ls [-l] [--col]           list drops (or collections with --col)
  cat <key>                 print clipboard drop content
  rm <key> / rm -f <key>   delete a drop
  cp <key> <new>            duplicate a drop
  mv <key> <new>            rename a drop
  cd <slug>                 change into a collection (context for add/rm)
  cd ..                     leave current collection
  pwd                       show current collection
  add <key>                 add drop to current collection (must cd first)
  open <key>                print the URL for a drop
  status <key>              view count and last seen
  help                      list available commands
  exit / quit / ^D          leave the shell

  All other drp commands (up, get, edit, save, etc.) are also available
  directly; they are delegated to the same handlers as the top-level CLI.

Pipe subset (inline, no bash delegation):
  <cmd> | grep <pattern>
  <cmd> | sort
  <cmd> | head [n]
  <cmd> | tail [n]
"""

import re
import sys

from cli.commands._context import load_context
from cli.api.helpers import err, ok

# Sentinel for commands _dispatch does not handle natively.
_NOT_HANDLED = object()

# ── Shell command names for autocomplete ──────────────────────────────────────
# Built-in shell commands
_BUILTIN_CMDS = [
    'ls', 'cat', 'rm', 'cp', 'mv', 'add', 'open', 'status',
    'cd', 'pwd', 'help', 'exit', 'quit',
]

# Delegated drp commands (handled by the top-level CLI parser/handlers)
_DELEGATED_CMDS = [
    'up', 'get', 'edit', 'save', 'renew', 'serve',
    'collection', 'token', 'ask', 'load', 'ping',
    'setup', 'login', 'logout', 'cache', 'rmcache',
]

ALL_SHELL_CMDS = sorted(set(_BUILTIN_CMDS + _DELEGATED_CMDS))

# Sub-commands for multi-level completion
_SUB_CMDS = {
    'collection': ['ls', 'new', 'add', 'rm', 'open'],
    'token':      ['create', 'list', 'revoke'],
}

# Commands whose first positional arg is a drop key
_KEY_CMDS = {
    'cat', 'rm', 'cp', 'mv', 'add', 'open', 'status',
    'get', 'edit', 'save', 'renew',
}

# Commands whose first positional arg is a collection slug
_SLUG_CMDS = {'cd'}


def cmd_shell(args):
    from cli.format import bold, dim, cyan, magenta, green, red, grey, yellow

    cfg, host, session = load_context(require_login=True)

    username = cfg.get('username', '')
    cwd = None

    version_line = dim(f'drp shell  —  type {bold("help")} for commands, ^D to exit')
    print(version_line)
    print()

    def prompt():
        if cwd:
            return f'{magenta("@" + username + "/" + cwd)}> '
        return f'{cyan("drp")}> '

    def _run_line(line, cwd):
        """Parse and execute one shell line. Returns updated cwd."""
        line = line.strip()
        if not line or line.startswith('#'):
            return cwd

        # ── Pipe splitting ────────────────────────────────────────────────────
        pipe_filter = None
        if ' | ' in line:
            parts       = line.split(' | ', 1)
            line        = parts[0].strip()
            pipe_filter = parts[1].strip()

        tokens = line.split()
        cmd    = tokens[0].lower()
        rest   = tokens[1:]

        output_lines = _dispatch(cmd, rest, host, session, cfg, cwd, username)

        if output_lines is None:
            return cwd  # command handled output itself (cd, pwd, help, exit)

        # ── Apply pipe filter ─────────────────────────────────────────────────
        if pipe_filter:
            output_lines = _apply_pipe(output_lines, pipe_filter)

        for ln in output_lines:
            print(ln)

        # cd returns new cwd through a sentinel
        return cwd

    # ── REPL loop ─────────────────────────────────────────────────────────────
    try:
        import readline

        def _completer(text, state):
            """Context-aware tab completer for the shell."""
            try:
                buf = readline.get_line_buffer().lstrip()
                tokens = buf.split()

                # Completing the first word → command names
                if not tokens or (len(tokens) == 1 and not buf.endswith(' ')):
                    matches = [c + ' ' for c in ALL_SHELL_CMDS if c.startswith(text)]
                else:
                    cmd = tokens[0].lower()
                    # Sub-command completion (collection ls/new/add/rm, token create/list/revoke)
                    if cmd in _SUB_CMDS and len(tokens) <= 2 and not (len(tokens) == 2 and buf.endswith(' ')):
                        matches = [s + ' ' for s in _SUB_CMDS[cmd] if s.startswith(text)]
                    # Drop key completion
                    elif cmd in _KEY_CMDS:
                        from cli.completion import _read_cache
                        matches = [k + ' ' for k in _read_cache(None, text)]
                    # Collection slug completion
                    elif cmd in _SLUG_CMDS:
                        from cli.completion import _read_collection_cache
                        matches = [s + ' ' for s in _read_collection_cache(text)]
                    else:
                        matches = []

                return matches[state] if state < len(matches) else None
            except Exception:
                return None

        readline.set_completer(_completer)
        readline.set_completer_delims(' \t')
        readline.parse_and_bind('tab: complete')
    except ImportError:
        pass

    while True:
        try:
            try:
                line = input(prompt())
            except EOFError:
                print()
                break

            tokens = line.strip().split()
            if not tokens:
                continue

            cmd = tokens[0].lower()

            # ── cd is special — it mutates cwd ────────────────────────────────
            if cmd == 'cd':
                target = tokens[1] if len(tokens) > 1 else ''
                if not target or target == '~':
                    cwd = None
                elif target == '..':
                    cwd = None
                else:
                    # Validate slug exists
                    slug = target.lstrip('@').split('/')[-1]
                    if username:
                        try:
                            res = session.get(
                                f'{host}/@{username}/{slug}/',
                                headers={'Accept': 'application/json'},
                                timeout=8,
                            )
                            if res.ok:
                                cwd = slug
                                print(f'  {dim("now in")} {magenta("@" + username + "/" + slug)}')
                            else:
                                print(f'  {red("✗")} collection "{slug}" not found.')
                        except Exception as e:
                            print(f'  {red("✗")} {e}')
                    else:
                        print(f'  {red("✗")} no username set. Run: drp login')
                continue

            # ── pwd ───────────────────────────────────────────────────────────
            if cmd == 'pwd':
                if cwd:
                    print(f'  {magenta("@" + username + "/" + cwd)}')
                else:
                    print(f'  {dim("(root — no collection selected)")}')
                continue

            # ── exit ──────────────────────────────────────────────────────────
            if cmd in ('exit', 'quit', 'q'):
                break

            # ── help ──────────────────────────────────────────────────────────
            if cmd == 'help':
                _print_shell_help()
                continue

            # ── Pipe splitting ────────────────────────────────────────────────
            pipe_filter = None
            if ' | ' in line:
                parts, line_part = line.split(' | ', 1), line
                cmd_part        = parts[0].strip()
                pipe_filter     = ' | '.join(line.split(' | ')[1:]).strip()
                tokens          = cmd_part.split()
                cmd             = tokens[0].lower()
                rest            = tokens[1:]
            else:
                rest = tokens[1:]

            output_lines = _dispatch(cmd, rest, host, session, cfg, cwd, username)

            if output_lines is None:
                continue  # command handled its own output

            # _dispatch returns _NOT_HANDLED for unknown native commands;
            # delegate them to the top-level CLI parser/handlers.
            if output_lines is _NOT_HANDLED:
                _delegate_to_cli(cmd, rest)
                continue

            if pipe_filter:
                output_lines = _apply_pipe(output_lines, pipe_filter)

            for ln in output_lines:
                print(ln)

        except KeyboardInterrupt:
            print()
            continue


def _dispatch(cmd, rest, host, session, cfg, cwd, username):
    """
    Execute a shell command. Returns a list of output lines, or None if the
    command handled its own printing (or is unknown).
    """
    from cli.format import cyan, blue, magenta, dim, green, red, grey, yellow, bold

    # ── ls ────────────────────────────────────────────────────────────────────
    if cmd == 'ls':
        long_fmt  = '-l' in rest
        col_mode  = '--col' in rest
        keys_only = [r for r in rest if not r.startswith('-')]

        if col_mode:
            return _ls_collections(host, session, cfg, username)

        if cwd:
            return _ls_collection_drops(host, session, cfg, username, cwd)

        return _ls_drops(host, session, long_fmt)

    # ── cat ───────────────────────────────────────────────────────────────────
    if cmd == 'cat':
        if not rest:
            return [f'  {red("✗")} Usage: cat <key>']
        key = rest[0]
        try:
            res = session.get(f'{host}/{key}/', headers={'Accept': 'application/json'}, timeout=10)
            if res.status_code == 401:
                # Password-protected drop — prompt and retry
                import getpass as _getpass
                try:
                    pw = _getpass.getpass(f'  Password for /{key}/: ')
                except (EOFError, KeyboardInterrupt):
                    return [f'  {dim("[cancelled]")}']
                res = session.get(
                    f'{host}/{key}/',
                    headers={'Accept': 'application/json', 'X-Drop-Password': pw},
                    timeout=10,
                )
                if res.status_code == 401:
                    return [f'  {red("✗")} wrong password.']
            if res.ok:
                data = res.json()
                if data.get('kind') == 'text':
                    return data.get('content', '').splitlines()
                return [f'  {dim("[file drop — use: drp get -f " + key + "]")}']
            return [f'  {red("✗")} {res.status_code}: drop not found.']
        except Exception as e:
            return [f'  {red("✗")} {e}']

    # ── rm ────────────────────────────────────────────────────────────────────
    if cmd == 'rm':
        is_file = '-f' in rest
        keys    = [r for r in rest if not r.startswith('-')]
        if not keys:
            return [f'  {red("✗")} Usage: rm [-f] <key>']
        key = keys[0]
        ns  = 'f' if is_file else 'c'
        from cli.api.actions import delete
        from cli.api.auth import get_csrf
        csrf = get_csrf(host, session)
        ok_result = delete(host, session, key, ns)
        if ok_result:
            return [f'  {green("✓")} {key}  deleted']
        return []  # delete() already printed the error

    # ── cp ────────────────────────────────────────────────────────────────────
    if cmd == 'cp':
        is_file = '-f' in rest
        keys    = [r for r in rest if not r.startswith('-')]
        if len(keys) < 2:
            return [f'  {red("✗")} Usage: cp [-f] <key> <new_key>']
        key, new_key = keys[0], keys[1]
        ns = 'f' if is_file else 'c'
        try:
            from cli.api.auth import get_csrf
            import json as _json
            csrf = get_csrf(host, session)
            res  = session.post(
                f'{host}/{"f/" if ns == "f" else ""}{key}/copy/',
                data=_json.dumps({'new_key': new_key}),
                headers={'X-CSRFToken': csrf, 'Content-Type': 'application/json'},
                timeout=10,
            )
            if res.ok:
                return [f'  {green("✓")} {key}  →  {cyan(new_key)}']
            try:
                msg = res.json().get('error', str(res.status_code))
            except Exception:
                msg = str(res.status_code)
            return [f'  {red("✗")} {msg}']
        except Exception as e:
            return [f'  {red("✗")} {e}']

    # ── mv ────────────────────────────────────────────────────────────────────
    if cmd == 'mv':
        is_file = '-f' in rest
        keys    = [r for r in rest if not r.startswith('-')]
        if len(keys) < 2:
            return [f'  {red("✗")} Usage: mv [-f] <key> <new_key>']
        key, new_key = keys[0], keys[1]
        ns = 'f' if is_file else 'c'
        from cli.api.actions import rename
        result = rename(host, session, key, new_key, ns)
        if result:
            return [f'  {green("✓")} {key}  →  {cyan(result)}']
        return []

    # ── add (to current collection) ───────────────────────────────────────────
    if cmd == 'add':
        if not cwd:
            return [f'  {red("✗")} cd into a collection first: cd <slug>']
        is_file = '-f' in rest
        keys    = [r for r in rest if not r.startswith('-')]
        if not keys:
            return [f'  {red("✗")} Usage: add [-f] <key>']
        key = keys[0]
        ns  = 'f' if is_file else 'c'
        return _collection_add(host, session, username, cwd, ns, key)

    # ── open ──────────────────────────────────────────────────────────────────
    if cmd == 'open':
        if not rest:
            return [f'  {red("✗")} Usage: open <key>']
        key     = rest[0]
        is_file = '-f' in rest
        prefix  = 'f/' if is_file else ''
        return [f'  {host}/{prefix}{key}/']

    # ── status ────────────────────────────────────────────────────────────────
    if cmd == 'status':
        if not rest:
            from cli.commands.status import cmd_status
            import argparse
            cmd_status(argparse.Namespace(key=None, file=False, clip=False))
            return None
        key = rest[0]
        try:
            res = session.get(f'{host}/{key}/', headers={'Accept': 'application/json'}, timeout=10)
            if res.ok:
                data    = res.json()
                views   = data.get('view_count', 0)
                last    = data.get('last_viewed_at', '')
                created = data.get('created_at', '')
                from cli.format import human_time
                return [
                    f'  {dim("key")}       {cyan(key)}',
                    f'  {dim("views")}     {green(str(views)) if views else dim("0")}',
                    f'  {dim("last seen")} {human_time(last) if last else dim("never")}',
                    f'  {dim("created")}   {human_time(created)}',
                ]
            return [f'  {red("✗")} {res.status_code}']
        except Exception as e:
            return [f'  {red("✗")} {e}']

    # ── Delegate to top-level CLI handler if recognized ─────────────────────
    return _NOT_HANDLED


def _delegate_to_cli(cmd, rest):
    """
    Run a drp CLI command by reusing the top-level parser and handler.
    Returns True if the command was handled, False if not a valid drp command.
    """
    from cli.drp import build_parser, _HANDLERS

    if cmd not in _HANDLERS:
        from cli.format import red
        print(f'  {red("✗")} unknown command: {cmd}  (type help)')
        return False

    try:
        parser = build_parser()
        args = parser.parse_args([cmd] + list(rest))
        _HANDLERS[cmd](args)
    except SystemExit:
        pass  # argparse calls sys.exit on --help or bad args
    except Exception as e:
        from cli.format import red
        print(f'  {red("✗")} {e}')
    return True


def _ls_drops(host, session, long_fmt):
    from cli.format import cyan, blue, grey, dim, yellow
    try:
        res = session.get(
            f'{host}/auth/account/',
            headers={'Accept': 'application/json'},
            timeout=15,
        )
        res.raise_for_status()
        data  = res.json()
        drops = data.get('drops', [])
        saved = data.get('saved', [])
    except Exception as e:
        return [f'  ✗ {e}']

    lines = []
    for d in drops:
        key_str = blue(f'f/{d["key"]}') if d['ns'] == 'f' else cyan(d['key'])
        lock    = yellow(' 🔒') if d.get('locked') else ''
        if long_fmt:
            from cli.commands.ls import _since, _until
            size    = d.get('filesize', 0)
            size_s  = f'{size}B' if size else '—'
            created = _since(d.get('created_at'))
            expires = _until(d.get('expires_at')) if d.get('expires_at') else grey('idle')
            lines.append(f'  {key_str}{lock}  {grey(size_s):>8}  {grey(created):>10}  {dim(expires)}')
        else:
            lines.append(f'  {key_str}{lock}')

    if drops and saved:
        lines.append('')

    for s in saved:
        key_str = blue(f'f/{s["key"]}') if s['ns'] == 'f' else cyan(s['key'])
        lines.append(f'  {key_str}  {dim("[saved]")}')

    return lines or [dim('  (no drops)')]


def _ls_collections(host, session, cfg, username):
    from cli.format import magenta, dim, grey
    try:
        res = session.get(
            f'{host}/auth/account/',
            headers={'Accept': 'application/json'},
            timeout=15,
        )
        res.raise_for_status()
        cols = res.json().get('collections', [])
    except Exception as e:
        return [f'  ✗ {e}']

    if not cols:
        return [dim('  (no collections)')]

    lines = []
    for col in cols:
        slug       = col.get('slug', '')
        name       = col.get('name', slug)
        drop_count = len(col.get('drops', []))
        prefix     = f'@{username}/' if username else ''
        lines.append(
            f'  {magenta(prefix + slug):<32}  {dim(name):<20}  '
            f'{grey(str(drop_count) + " drop" + ("s" if drop_count != 1 else ""))}'
        )
    return lines


def _ls_collection_drops(host, session, cfg, username, slug):
    from cli.format import cyan, blue, dim, grey, red
    try:
        res = session.get(
            f'{host}/@{username}/{slug}/',
            headers={'Accept': 'application/json'},
            timeout=10,
        )
        if not res.ok:
            return [f'  {red("✗")} collection not found.']
        drops = res.json().get('drops', [])
    except Exception as e:
        return [f'  {red("✗")} {e}']

    if not drops:
        return [dim('  (empty collection)')]

    lines = []
    for d in drops:
        key_str = blue(f'f/{d["key"]}') if d['ns'] == 'f' else cyan(d['key'])
        lines.append(f'  {key_str}')
    return lines


def _collection_add(host, session, username, slug, ns, key):
    from cli.format import green, red, magenta, cyan, blue
    from cli.api.auth import get_csrf
    import json as _json

    try:
        detail = session.get(
            f'{host}/@{username}/{slug}/',
            headers={'Accept': 'application/json'},
            timeout=8,
        )
        if not detail.ok:
            return [f'  {red("✗")} collection "{slug}" not found.']
        collection_id = detail.json().get('id')
    except Exception as e:
        return [f'  {red("✗")} {e}']

    try:
        csrf = get_csrf(host, session)
        res  = session.post(
            f'{host}/collections/{collection_id}/add/',
            data=_json.dumps({'ns': ns, 'key': key}),
            headers={'X-CSRFToken': csrf, 'Content-Type': 'application/json'},
            timeout=10,
        )
        if res.ok:
            key_str = blue(f'f/{key}') if ns == 'f' else cyan(key)
            return [f'  {green("✓")} {key_str}  →  {magenta(slug)}']
        try:
            msg = res.json().get('error', str(res.status_code))
        except Exception:
            msg = str(res.status_code)
        return [f'  {red("✗")} {msg}']
    except Exception as e:
        return [f'  {red("✗")} {e}']


def _apply_pipe(lines, pipe_expr):
    """Apply a simple pipe filter to a list of output lines."""
    tokens = pipe_expr.split()
    if not tokens:
        return lines

    cmd = tokens[0].lower()

    if cmd == 'grep' and len(tokens) > 1:
        pattern = tokens[1]
        try:
            regex = re.compile(pattern, re.IGNORECASE)
            return [ln for ln in lines if regex.search(ln)]
        except re.error:
            return [ln for ln in lines if pattern.lower() in ln.lower()]

    if cmd == 'sort':
        return sorted(lines)

    if cmd == 'head':
        n = int(tokens[1]) if len(tokens) > 1 and tokens[1].isdigit() else 10
        return lines[:n]

    if cmd == 'tail':
        n = int(tokens[1]) if len(tokens) > 1 and tokens[1].isdigit() else 10
        return lines[-n:]

    # Unknown pipe command — pass through
    return lines


def _print_shell_help():
    from cli.format import bold, dim, cyan, magenta, green

    print(f'  {bold("drp shell commands")}')
    print(f'  {dim("─" * 40)}')
    cmds = [
        ('ls [-l]',           'list drops'),
        ('ls --col',          'list collections'),
        ('cat <key>',         'print clipboard content'),
        ('rm [-f] <key>',     'delete a drop'),
        ('cp [-f] <src> <dst>', 'duplicate a drop'),
        ('mv [-f] <src> <dst>', 'rename a drop'),
        ('cd <slug>',         'enter a collection'),
        ('cd ..',             'leave collection'),
        ('pwd',               'show current collection'),
        ('add [-f] <key>',    'add drop to current collection'),
        ('open <key>',        'print drop URL'),
        ('status <key>',      'view count and last seen'),
        ('exit',              'leave the shell'),
    ]
    w = max(len(c) for c, _ in cmds) + 2
    for cmd_name, desc in cmds:
        print(f'    {cyan(cmd_name):<{w + 10}}  {dim(desc)}')

    print()
    print(f'  {bold("all drp commands are also available")}')
    print(f'  {dim("─" * 40)}')
    delegated = [
        ('up <target>',        'upload text or file'),
        ('get <key>',          'fetch a drop'),
        ('edit <key>',         'edit in $EDITOR'),
        ('save <key>',         'bookmark a drop'),
        ('renew <key>',        'renew expiry'),
        ('serve <targets>',    'upload dir / file list'),
        ('collection <cmd>',   'manage collections'),
        ('token <cmd>',        'manage API tokens'),
        ('ask <question>',     'ask the help bot'),
        ('load <file>',        'import exported drops'),
        ('ping',               'check connectivity'),
    ]
    for cmd_name, desc in delegated:
        print(f'    {cyan(cmd_name):<{w + 10}}  {dim(desc)}')
    print()
    print(f'  {dim("pipe subset:")}  grep · sort · head · tail')
    print(f'  {dim("example:")}      ls | grep notes')
    print(f'  {dim("tab:")}          press tab to autocomplete commands and keys')
    print()