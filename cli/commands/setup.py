"""
Setup, login, and logout commands.
"""

import getpass
import os
import subprocess
import sys
from pathlib import Path

import requests

from cli import config, api, DEFAULT_HOST
from cli.session import save_session, clear_session, auto_login
from cli.path_check import check_scripts_in_path


def cmd_setup(args):
    cfg = config.load()
    print('drp setup')
    print('─────────')
    default = cfg.get('host', DEFAULT_HOST)
    cfg['host'] = input(f'  Host [{default}]: ').strip() or default
    config.save(cfg)
    _setup_ansi(cfg)
    answer = input('  Log in now? (y/n) [y]: ').strip().lower()
    if answer != 'n':
        cmd_login(args)
    check_scripts_in_path()
    _setup_completion()
    print(f'\n  ✓ Config saved to {config.CONFIG_FILE}')


def _setup_ansi(cfg: dict) -> None:
    """
    Detect ANSI color support, enable it on Windows if possible, and persist
    the result as cfg['ansi']. Writes config to disk before returning.

    Respects NO_COLOR env var (no-color.org).
    """
    # NO_COLOR always wins
    if os.environ.get('NO_COLOR'):
        cfg['ansi'] = False
        config.save(cfg)
        print('  Color:     disabled (NO_COLOR set)')
        return

    supported = False

    if sys.platform == 'win32':
        # The empty os.system('') call activates ANSI processing in the
        # legacy Windows console. Then we verify via the console mode flag.
        os.system('')
        try:
            import ctypes
            ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
            STD_OUTPUT_HANDLE = -11
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
            mode = ctypes.c_ulong()
            kernel32.GetConsoleMode(handle, ctypes.byref(mode))
            if not (mode.value & ENABLE_VIRTUAL_TERMINAL_PROCESSING):
                # Try to enable it
                kernel32.SetConsoleMode(
                    handle, mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING
                )
                kernel32.GetConsoleMode(handle, ctypes.byref(mode))
            supported = bool(mode.value & ENABLE_VIRTUAL_TERMINAL_PROCESSING)
        except Exception:
            supported = False
    else:
        supported = sys.stdout.isatty()

    cfg['ansi'] = supported
    config.save(cfg)

    status = '✓ enabled' if supported else '✗ not supported (plain output)'
    print(f'  Color:     {status}')


def cmd_login(args):
    cfg = config.load()
    host = cfg.get('host', DEFAULT_HOST)

    # --token: store an API token instead of session login
    token = getattr(args, 'token', None)
    if token:
        cfg['api_key'] = token
        config.save(cfg)
        # Validate the token by hitting the account endpoint
        session = requests.Session()
        session.headers['Authorization'] = f'Bearer {token}'
        try:
            res = session.get(
                f'{host}/auth/account/',
                headers={'Accept': 'application/json'},
                timeout=10,
            )
            if res.ok:
                account = res.json()
                username = account.get('username', '')
                if username:
                    cfg['username'] = username
                    config.save(cfg)
                print(f'  ✓ Token saved — authenticated as @{username or "?"}')
                # Populate completion cache after token login
                from cli.completion import sync_completions
                sync_completions(host=host, session=session)
            else:
                print(f'  ✗ Token rejected (HTTP {res.status_code})')
                cfg.pop('api_key', None)
                config.save(cfg)
                sys.exit(1)
        except Exception as e:
            print(f'  ✗ Could not validate token: {e}')
            cfg.pop('api_key', None)
            config.save(cfg)
            sys.exit(1)
        return

    identifier = input('  Username or email: ').strip()
    password = getpass.getpass('  Password: ')
    session = requests.Session()
    try:
        if api.login(host, session, identifier, password):
            cfg['email'] = identifier
            # Fetch username from account endpoint
            try:
                res = session.get(
                    f'{host}/auth/account/',
                    headers={'Accept': 'application/json'},
                    timeout=10,
                )
                if res.ok:
                    account = res.json()
                    username = account.get('username', '')
                    email = account.get('email', '')
                    if username:
                        cfg['username'] = username
                    if email:
                        cfg['email'] = email
            except Exception:
                pass
            config.save(cfg)
            save_session(session)
            username_str = f' (@{cfg["username"]})' if cfg.get('username') else ''
            print(f'  ✓ Logged in as {cfg["email"]}{username_str}')
            # Populate completion cache after login
            from cli.completion import sync_completions
            sync_completions(host=host, session=session)
        else:
            print('  ✗ Login failed — check your credentials.')
            sys.exit(1)
    except Exception as e:
        print(f'  ✗ Login error: {e}')
        sys.exit(1)


def cmd_logout(args):
    cfg = config.load()
    email = cfg.pop('email', None)
    config.save(cfg)
    clear_session()
    print(f'  ✓ Logged out ({email})' if email else '  (already anonymous)')


# ── Completion setup ──────────────────────────────────────────────────────────

def _setup_completion():
    print()
    print('  Tab completion')
    print('  ──────────────')

    if not _argcomplete_available():
        print('  Installing argcomplete…', end=' ', flush=True)
        ok = _install_argcomplete()
        if ok:
            print('done')
        else:
            print('failed')
            _print_manual_install_hint()
            return
    else:
        print('  argcomplete already installed  ✓')

    shell, profile = _detect_shell_and_profile()
    activation = _activation_line(shell)

    if not activation:
        print(f'  Unknown shell ({shell!r}) — see below for manual setup.')
        _print_manual_fallback()
        return

    if profile:
        if _profile_has_activation(profile, activation):
            print(f'  Shell profile already configured  ✓')
        else:
            if _append_to_profile(profile, activation):
                print(f'  Written to {profile}  ✓')
            else:
                print(f'  Could not write to {profile}')
                _print_manual_activation_hint(shell, activation)
                return
    else:
        _print_manual_activation_hint(shell, activation)
        return

    print(f'  Restart your shell (or: source {profile}) to activate.')


def _argcomplete_available() -> bool:
    try:
        import argcomplete  # noqa: F401
        return True
    except ImportError:
        return False


def _install_argcomplete() -> bool:
    if os.environ.get('PIPX_HOME') or _pipx_available():
        result = subprocess.run(
            ['pipx', 'inject', 'drp-dev', 'argcomplete'],
            capture_output=True,
        )
        if result.returncode == 0:
            return True

    result = subprocess.run(
        [sys.executable, '-m', 'pip', 'install', '--quiet', 'argcomplete'],
        capture_output=True,
    )
    return result.returncode == 0


def _pipx_available() -> bool:
    try:
        result = subprocess.run(['pipx', '--version'], capture_output=True)
        return result.returncode == 0
    except FileNotFoundError:
        return False


def _detect_shell_and_profile() -> tuple[str, str | None]:
    shell_path = os.environ.get('SHELL', '')
    shell = os.path.basename(shell_path).lower()
    home = Path.home()

    candidates: dict[str, list[Path]] = {
        'bash': [home / '.bashrc', home / '.bash_profile'],
        'zsh':  [home / '.zshrc'],
        'fish': [home / '.config' / 'fish' / 'config.fish'],
    }

    for path in candidates.get(shell, []):
        if path.exists():
            return shell, str(path)

    first = candidates.get(shell, [None])[0]
    return shell, str(first) if first else None


def _activation_line(shell: str) -> str | None:
    return {
        'bash': 'eval "$(register-python-argcomplete drp)"',
        'zsh':  (
            'autoload -U bashcompinit && bashcompinit && '
            'eval "$(register-python-argcomplete drp)"'
        ),
        'fish': 'register-python-argcomplete --shell fish drp | source',
    }.get(shell)


def _profile_has_activation(profile_path: str, activation: str) -> bool:
    try:
        return activation in Path(profile_path).read_text()
    except Exception:
        return False


def _append_to_profile(profile_path: str, activation: str) -> bool:
    try:
        p = Path(profile_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open('a') as f:
            f.write(f'\n# drp tab completion\n{activation}\n')
        return True
    except Exception:
        return False


def _print_manual_install_hint():
    print()
    print('  Install argcomplete manually, then re-run drp setup:')
    print('    pipx inject drp-dev argcomplete')
    print('    # or: pip install argcomplete')


def _print_manual_activation_hint(shell: str, activation: str):
    print()
    print('  Add this line to your shell profile and restart your shell:')
    print(f'    {activation}')


def _print_manual_fallback():
    print()
    print('  Supported shells: bash, zsh, fish.')
    print('  Add the appropriate line to your shell profile:')
    print()
    print('    bash / zsh:')
    print('      eval "$(register-python-argcomplete drp)"')
    print('    fish:')
    print('      register-python-argcomplete --shell fish drp | source')