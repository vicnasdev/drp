"""
drp shell — interactive REPL.

Commands available inside the shell:

  ls [-l] [--col]           list drops (or folders with --col)
  cat <key>                 print clipboard drop content
  rm <key>                      delete a drop
  cp <key> <new>            duplicate a drop
  mv <key> <new>            rename a drop
  cd <slug>                 change into a folder (context for add/rm)
  cd ..                     leave current folder
  pwd                       show current folder
  add <key>                 add drop to current folder (must cd first)
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
import shlex
import sys

from cli.commands._context import load_context
from cli.api.helpers import err, ok

# Sentinel for commands _dispatch does not handle natively.
_NOT_HANDLED = object()

# ── Shell command names for autocomplete ──────────────────────────────────────
# Built-in shell commands
_BUILTIN_CMDS = [
    'ls', 'cat', 'rm', 'cp', 'mv', 'add', 'open', 'status',
    'save', 'renew', 'lock', 'mkdir', 'info', 'rekey',
    'cd', 'pwd', 'clear', 'help', 'exit', 'quit', 'link', 'getlink',
]

# Delegated drp commands (handled by the top-level CLI parser/handlers)
_DELEGATED_CMDS = [
    'up', 'get', 'ls',
    'token', 'ask', 'ping',
    'setup', 'login', 'logout',
]

ALL_SHELL_CMDS = sorted(set(_BUILTIN_CMDS + _DELEGATED_CMDS))

# Sub-commands for multi-level completion
_SUB_CMDS = {
    'token':  ['create', 'list', 'revoke'],
}

# Commands whose first positional arg is a drop key
_KEY_CMDS = {
    'cat', 'rm', 'cp', 'mv', 'add', 'open', 'status',
    'get', 'save', 'renew', 'lock',
}

# Commands whose first positional arg is a folder slug
_SLUG_CMDS = {'cd'}


def cmd_shell(args):
    from cli.format import bold, dim, cyan, magenta, green, red, grey, yellow

    cfg, host, session = load_context(require_login=True)

    username = cfg.get('username', '')
    cwd = None  # Current folder path (e.g. 'notes' or 'notes/work')

    version_line = dim(f'drp shell  —  type {bold("help")} for commands, ^D to exit')
    print(version_line)
    print()

    def prompt():
        if cwd:
            return f'{magenta("@" + username + "/" + cwd)}> '
        return f'{cyan("drp")}> '

    def _resolve_folder_path(target):
        """Resolve a target path relative to cwd. Returns full path or None."""
        if target.startswith('/') or target.startswith('@'):
            # Absolute path
            return target.lstrip('@').lstrip('/').rstrip('/')
        if cwd:
            return f'{cwd}/{target}'.rstrip('/')
        return target.rstrip('/')

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

        try:
            tokens = shlex.split(line)
        except ValueError:
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
                    # Sub-command completion (folder ls/new/add/rm, token create/list/revoke)
                    if cmd in _SUB_CMDS and len(tokens) <= 2 and not (len(tokens) == 2 and buf.endswith(' ')):
                        matches = [s + ' ' for s in _SUB_CMDS[cmd] if s.startswith(text)]
                    # Drop key completion
                    elif cmd in _KEY_CMDS:
                        from cli.completion import _read_cache
                        matches = [k + ' ' for k in _read_cache(None, text)]
                    # Folder slug completion
                    elif cmd in _SLUG_CMDS:
                        from cli.completion import _read_folder_cache
                        matches = [s + ' ' for s in _read_folder_cache(text)]
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

            try:
                tokens = shlex.split(line.strip())
            except ValueError:
                tokens = line.strip().split()
            if not tokens:
                continue

            # Strip leading 'drp' prefix — users may type "drp up" instead of "up"
            if tokens[0].lower() == 'drp' and len(tokens) > 1:
                tokens = tokens[1:]

            cmd = tokens[0].lower()

            # ── cd is special — it mutates cwd ────────────────────────────────
            if cmd == 'cd':
                target = tokens[1] if len(tokens) > 1 else ''
                if not target or target == '~':
                    cwd = None
                elif target == '..':
                    if cwd and '/' in cwd:
                        cwd = cwd.rsplit('/', 1)[0]
                    else:
                        cwd = None
                else:
                    # Resolve relative or absolute path
                    full_path = _resolve_folder_path(target)
                    if username:
                        try:
                            res = session.get(
                                f'{host}/@{username}/{full_path}/',
                                headers={'Accept': 'application/json'},
                                timeout=8,
                            )
                            if res.ok:
                                cwd = full_path
                                print(f'  {dim("now in")} {magenta("@" + username + "/" + full_path)}')
                            else:
                                print(f'  {red("✗")} folder "{full_path}" not found.')
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
                    print(f'  {dim("(root — no folder selected)")}')
                continue

            # ── clear ─────────────────────────────────────────────────────
            if cmd == 'clear':
                import os as _os
                _os.system('clear' if sys.platform != 'win32' else 'cls')
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
                try:
                    tokens      = shlex.split(cmd_part)
                except ValueError:
                    tokens      = cmd_part.split()
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
                _delegate_to_cli(cmd, rest, cwd=cwd, host=host,
                                 session=session, username=username)
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
        col_mode  = '--col' in rest
        long_mode = '-l' in rest

        # Inside a folder → show that folder's drops
        if cwd and not col_mode:
            return _ls_folder_drops(host, session, cfg, username, cwd, long_mode=long_mode)

        # Otherwise delegate to the real CLI handler (supports -l, --col, etc.)
        _delegate_to_cli(cmd, rest, cwd=cwd, host=host, session=session, username=username)
        return None

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
                return [f'  {dim("[file drop — use: drp get " + key + "]")}']
            return [f'  {red("✗")} {res.status_code}: drop not found.']
        except Exception as e:
            return [f'  {red("✗")} {e}']

    # ── rm — delete drop inline ───────────────────────────────────────────────
    if cmd == 'rm':
        if not rest:
            return [f'  {red("✗")} Usage: rm <key>']
        key = rest[0]
        try:
            from cli.api.actions import delete
            ok = delete(host, session, key)
            if ok:
                return [f'  {green("✓")} Deleted /{key}/']
            return [f'  {red("✗")} Could not delete /{key}/.']
        except Exception as e:
            return [f'  {red("✗")} {e}']

    # ── cp — copy drop or upload local file ───────────────────────────────
    if cmd == 'cp':
        if not rest:
            return [f'  {red("✗")} Usage: cp <key> [new_key]  or  cp <local_file> .']
        src = rest[0]
        dst = rest[1] if len(rest) > 1 else None

        # Detect local file paths: ./foo, ../foo, /abs/path, ~/path,
        # or anything containing / or with a file extension
        import os
        is_local = (
            src.startswith('./')  or src.startswith('../')
            or src.startswith('/') or src.startswith('~')
            or (os.sep in src and os.path.exists(os.path.expanduser(src)))
        )
        if is_local:
            # Upload local file as a drop
            local_path = os.path.expanduser(src)
            if not os.path.exists(local_path):
                return [f'  {red("✗")} File not found: {src}']
            try:
                from cli.api.file import upload_file
                result = upload_file(host, session, local_path)
                if result:
                    new_key = result if isinstance(result, str) else result.get('key', '?')
                    from cli import config as _config
                    _config.record_drop(new_key, 'file', host=host)
                    # Auto-add to current folder if cd'd
                    if cwd and username:
                        _folder_add(host, session, username, cwd, new_key)
                    return [f'  {green("✓")} uploaded {os.path.basename(local_path)} → /{new_key}/']
                return [f'  {red("✗")} Upload failed.']
            except Exception as e:
                return [f'  {red("✗")} {e}']

        # Server-side copy of existing drop
        key = src
        new_key = dst
        try:
            from cli.api.actions import copy_drop
            result = copy_drop(host, session, key, new_key)
            if isinstance(result, str):
                from cli import config as _config
                _config.record_drop(result, 'text', host=host)
                return [f'  {green("✓")} /{key}/ → /{result}/']
            return [f'  {red("✗")} Could not copy /{key}/.']
        except Exception as e:
            return [f'  {red("✗")} {e}']

    # ── mv — rename drop inline ─────────────────────────────────────────────
    if cmd == 'mv':
        if len(rest) < 2:
            return [f'  {red("✗")} Usage: mv <key> <new_key>']
        key = rest[0]
        new_key = rest[1]
        try:
            from cli.api.actions import rename
            result = rename(host, session, key, new_key)
            if isinstance(result, str):
                from cli import config as _config
                _config.rename_local_drop(key, result)
                return [f'  {green("✓")} /{key}/ → /{result}/']
            return [f'  {red("✗")} Could not rename /{key}/.']
        except Exception as e:
            return [f'  {red("✗")} {e}']

    # ── save — bookmark drop ────────────────────────────────────────────────
    if cmd == 'save':
        if not rest:
            return [f'  {red("✗")} Usage: save <key>']
        key = rest[0]
        try:
            from cli.api.actions import save_bookmark as _save_bk
            ok = _save_bk(host, session, key)
            if ok:
                return [f'  {green("✓")} Bookmarked /{key}/']
            return [f'  {red("✗")} Could not bookmark /{key}/.']
        except Exception as e:
            return [f'  {red("✗")} {e}']

    # ── renew — renew expiry ────────────────────────────────────────────────
    if cmd == 'renew':
        if not rest:
            return [f'  {red("✗")} Usage: renew <key>']
        key = rest[0]
        try:
            from cli.api.actions import renew as _renew
            expires_at, renewals = _renew(host, session, key)
            if expires_at:
                from cli.format import human_time
                return [f'  {green("✓")} /{key}/ renewed → expires {human_time(expires_at)}']
            return [f'  {red("✗")} Could not renew /{key}/.']
        except Exception as e:
            return [f'  {red("✗")} {e}']

    # ── lock — set/remove password ──────────────────────────────────────────
    if cmd == 'lock':
        if not rest:
            return [f'  {red("✗")} Usage: lock <key> [--remove]']
        key = rest[0]
        remove = '--remove' in rest or '-r' in rest
        try:
            from cli.api.actions import lock_drop
            if remove:
                ok = lock_drop(host, session, key, remove=True)
                if ok:
                    return [f'  {green("✓")} Password removed from /{key}/']
            else:
                import getpass as _gp
                try:
                    pw = _gp.getpass(f'  Password for /{key}/: ')
                except (EOFError, KeyboardInterrupt):
                    return [f'  {dim("[cancelled]")}']
                ok = lock_drop(host, session, key, password=pw)
                if ok:
                    return [f'  {green("✓")} /{key}/ is now password-protected.']
            return [f'  {red("✗")} Could not update password on /{key}/.']
        except Exception as e:
            return [f'  {red("✗")} {e}']

    # ── mkdir — create folder ───────────────────────────────────────────────
    if cmd == 'mkdir':
        if not rest:
            return [f'  {red("✗")} Usage: mkdir <name>']
        name = rest[0]
        try:
            from cli.api.actions import create_folder as _mkdir
            parent_id = None
            if cwd and username:
                # Resolve current folder to get parent ID
                detail = session.get(
                    f'{host}/@{username}/{cwd}/',
                    headers={'Accept': 'application/json'}, timeout=8,
                )
                if detail.ok:
                    parent_id = detail.json().get('id')
            result = _mkdir(host, session, name, parent_id=parent_id)
            if result:
                slug = result.get('slug', name)
                return [f'  {green("✓")} Folder /{slug}/ created.']
            return [f'  {red("✗")} Could not create folder "{name}".']
        except Exception as e:
            return [f'  {red("✗")} {e}']

    # ── info — show drop details ────────────────────────────────────────────
    if cmd == 'info':
        if not rest:
            return [f'  {red("✗")} Usage: info <key>']
        key = rest[0]
        try:
            res = session.get(f'{host}/{key}/', headers={'Accept': 'application/json'}, timeout=10)
            if not res.ok:
                return [f'  {red("✗")} {res.status_code}: drop not found.']
            data = res.json()
            lines = [f'  {bold(key)}']
            lines.append(f'  kind:     {data.get("kind", "?")}')
            if data.get('filename'):
                lines.append(f'  filename: {data["filename"]}')
            if data.get('filesize'):
                lines.append(f'  size:     {data["filesize"]} bytes')
            if data.get('created_at'):
                lines.append(f'  created:  {data["created_at"]}')
            if data.get('expires_at'):
                lines.append(f'  expires:  {data["expires_at"]}')
            if data.get('view_count') is not None:
                lines.append(f'  views:    {data["view_count"]}')
            if data.get('locked') or data.get('password_protected'):
                lines.append(f'  locked:   {yellow("yes")}')
            if data.get('burn'):
                lines.append(f'  burn:     {red("yes")}')
            return lines
        except Exception as e:
            return [f'  {red("✗")} {e}']

    # ── rekey — change URL key (alias for mv) ───────────────────────────────
    if cmd == 'rekey':
        if len(rest) < 2:
            return [f'  {red("✗")} Usage: rekey <key> <new_key>']
        key = rest[0]
        new_key = rest[1]
        try:
            from cli.api.actions import rename
            result = rename(host, session, key, new_key)
            if isinstance(result, str):
                from cli import config as _config
                _config.rename_local_drop(key, result)
                return [f'  {green("✓")} /{key}/ → /{result}/']
            return [f'  {red("✗")} Could not rekey /{key}/.']
        except Exception as e:
            return [f'  {red("✗")} {e}']

    # ── add (to current folder) ─────────────────────────────────────────────
    if cmd == 'add':
        if not cwd:
            return [f'  {red("✗")} cd into a folder first: cd <slug>']
        keys    = [r for r in rest if not r.startswith('-')]
        if not keys:
            return [f'  {red("✗")} Usage: add <key>']
        key = keys[0]
        return _folder_add(host, session, username, cwd, key)

    # ── open ──────────────────────────────────────────────────────────────────
    if cmd == 'open':
        if not rest:
            return [f'  {red("✗")} Usage: open <key>']
        key     = rest[0]
        return [f'  {host}/{key}/']

    # ── link — print global or relative link ─────────────────────────────────
    if cmd in ('link', 'getlink'):
        if not rest:
            return [f'  {red("✗")} Usage: link <key> [--relative]']
        key = rest[0]
        relative = '--relative' in rest or '-r' in rest
        if relative:
            try:
                res = session.get(
                    f'{host}/{key}/',
                    headers={'Accept': 'application/json'},
                    timeout=10,
                )
                if not res.ok:
                    return [f'  {red("✗")} {res.status_code}: drop not found.']
                data = res.json()
                folder_path = data.get('folder_path')
                if not folder_path:
                    return [f'  {red("✗")} drop is not in any folder.']
                return [f'  {cyan(host + folder_path)}']
            except Exception as e:
                return [f'  {red("✗")} {e}']
        return [f'  {cyan(host + "/" + key + "/")}']

    # ── status — delegate to CLI handler ─────────────────────────────────────
    if cmd == 'status':
        _delegate_to_cli(cmd, rest, cwd=cwd, host=host, session=session, username=username)
        return None

    # ── Delegate to top-level CLI handler if recognized ─────────────────────
    return _NOT_HANDLED


def _delegate_to_cli(cmd, rest, *, cwd=None, host=None, session=None, username=None):
    """
    Run a drp CLI command by reusing the top-level parser and handler.
    When *cwd* (folder path) is set, uploads are auto-added to that folder.
    Returns True if the command was handled, False if not a valid drp command.
    """
    from cli.drp import build_parser, _HANDLERS

    if cmd not in _HANDLERS:
        from cli.format import red
        print(f'  {red("✗")} unknown command: {cmd}  (type help)')
        return False

    # Snapshot local drop list before the command runs
    drops_before = None
    if cwd and cmd in ('up', 'serve'):
        from cli.config import load_local_drops
        drops_before = {d['key'] for d in load_local_drops()}

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

    # Auto-add newly created drops to the current folder
    if drops_before is not None and host and session and username:
        from cli.config import load_local_drops
        from cli.format import dim, magenta
        new_drops = [d for d in load_local_drops() if d['key'] not in drops_before]
        for d in new_drops:
            result = _folder_add(host, session, username, cwd, d['key'])
            for ln in result:
                print(ln)

    return True


def _ls_folder_drops(host, session, cfg, username, path, long_mode=False):
    """List drops in a folder (supports nested sub-folder paths)."""
    from cli.format import cyan, blue, dim, grey, red, magenta, yellow
    from cli.commands.ls import _human, _since, _until
    try:
        res = session.get(
            f'{host}/@{username}/{path}/',
            headers={'Accept': 'application/json'},
            timeout=10,
        )
        if not res.ok:
            return [f'  {red("✗")} folder not found.']
        data = res.json()
        drops = data.get('drops', [])
        children = data.get('children', [])
    except Exception as e:
        return [f'  {red("✗")} {e}']

    lines = []

    # Show sub-folders first
    for child_slug in children:
        lines.append(f'  {magenta(child_slug + "/")}')

    if children and drops:
        lines.append('')

    if not drops and not children:
        return [dim('  (empty folder)')]

    if long_mode:
        # Fetch metadata for each drop to show details
        rows = []
        for d in drops:
            key = d.get('key', '') if isinstance(d, dict) else d
            try:
                detail = session.get(
                    f'{host}/{key}/',
                    headers={'Accept': 'application/json'},
                    timeout=8,
                )
                if detail.ok:
                    dd = detail.json()
                    is_file = dd.get('kind') == 'file'
                    fn = dd.get('filename') or ''
                    key_col = blue(key) if is_file else cyan(key)
                    lock = yellow('🔒') if dd.get('locked') or dd.get('password_protected') else '  '
                    size = _human(dd['filesize']) if is_file and dd.get('filesize') else '—'
                    created = _since(dd.get('created_at'))
                    expires = _until(dd.get('expires_at')) if dd.get('expires_at') else grey('idle')
                    rows.append((lock, fn, key_col, key, size, created, expires))
                else:
                    rows.append(('  ', '', cyan(key), key, '—', '—', '—'))
            except Exception:
                rows.append(('  ', '', cyan(key), key, '—', '—', '—'))

        if not rows:
            return [dim('  (empty folder)')]

        fn_w = max((len(r[1]) for r in rows), default=0)
        key_w = max((len(r[3]) for r in rows), default=4)
        size_w = max((len(r[4]) for r in rows), default=4)
        created_w = max((len(r[5]) for r in rows), default=7)

        for lock, fn, key_col, raw_key, size, created, expires in rows:
            key_pad = ' ' * max(0, key_w - len(raw_key))
            fn_part = ''
            if fn_w > 0:
                fn_pad = ' ' * max(0, fn_w - len(fn))
                fn_part = f'{fn}{fn_pad}  '
            lines.append(
                f'  {lock}  {fn_part}{key_col}{key_pad}  '
                f'{grey(size):>{size_w + 15}}  '
                f'{grey(created):>{created_w + 15}}  '
                f'{dim(expires)}'
            )
    else:
        for d in drops:
            key = d.get('key', '') if isinstance(d, dict) else d
            kind = d.get('kind', '') if isinstance(d, dict) else ''
            key_str = blue(key) if kind == 'file' else cyan(key)
            lines.append(f'  {key_str}')

    return lines or [dim('  (empty folder)')]


def _folder_add(host, session, username, slug, key):
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
            return [f'  {red("✗")} folder "{slug}" not found.']
        folder_id = detail.json().get('id')
    except Exception as e:
        return [f'  {red("✗")} {e}']

    try:
        csrf = get_csrf(host, session)
        res  = session.post(
            f'{host}/folders/{folder_id}/add/',
            data=_json.dumps({'key': key}),
            headers={'X-CSRFToken': csrf, 'Content-Type': 'application/json'},
            timeout=10,
        )
        if res.ok:
            return [f'  {green("✓")} {cyan(key)}  →  {magenta(slug)}']
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
        ('ls --col',          'list folders'),
        ('cat <key>',         'print clipboard content'),
        ('rm <key>',          'delete a drop'),
        ('cp <key> [new]',    'duplicate a drop'),
        ('mv <key> <new>',    'rename a drop'),
        ('save <key>',        'bookmark a drop'),
        ('renew <key>',       'renew expiry'),
        ('lock <key>',        'set password (--remove to clear)'),
        ('info <key>',        'show drop details'),
        ('rekey <key> <new>', 'change URL key'),
        ('mkdir <name>',      'create folder (nested if inside cd)'),
        ('cd <slug>',         'enter a folder'),
        ('cd parent/child',   'navigate into sub-folder'),
        ('cd ..',             'go up one level'),
        ('pwd',               'show current folder path'),
        ('add <key>',         'add drop to current folder'),
        ('open <key>',        'print drop URL'),
        ('link <key>',        'shareable link (--relative for folder path)'),
        ('status <key>',      'view count and last seen'),
        ('clear',             'clear the screen'),
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
        ('serve <targets>',    'upload dir / file list'),
        ('token <cmd>',        'manage API tokens'),
        ('ask <question>',     'ask the help bot'),
        ('ping',               'check connectivity'),
    ]
    for cmd_name, desc in delegated:
        print(f'    {cyan(cmd_name):<{w + 10}}  {dim(desc)}')
    print()
    print(f'  {dim("pipe subset:")}  grep · sort · head · tail')
    print(f'  {dim("example:")}      ls | grep notes')
    print(f'  {dim("tab:")}          press tab to autocomplete commands and keys')
    print()
    print(f'  {dim("context:")}      inside a folder, up/serve auto-add drops to it')
    print(f'  {dim("prefix:")}       you can type \"drp up\" or just \"up\" — both work')
    print()