#!/usr/bin/env python3
"""drp — drop clipboards and files from the command line. Run `drp --help`."""

import argparse
import sys

from cli import __version__
from cli.commands.setup import cmd_setup, cmd_login, cmd_logout
from cli.commands.upload import cmd_up
from cli.commands.get import cmd_get
from cli.commands.status import cmd_status, cmd_ping
from cli.commands.shell import cmd_shell
from cli.commands.token import cmd_token
from cli.commands.ask import cmd_ask
from cli.commands.getlink import cmd_getlink
from cli.commands.manage import cmd_rm, cmd_mv, cmd_renew, cmd_cp, cmd_save, cmd_lock, cmd_mkdir
from cli.commands.ls import cmd_ls

COMMANDS = [
    ('setup',      cmd_setup,       'Configure host and log in'),
    ('login',      cmd_login,       'Log in (session saved — no repeated prompts)'),
    ('logout',     cmd_logout,      'Log out and clear saved session'),
    ('ping',       cmd_ping,        'Check connectivity to the drp server'),
    ('status',     cmd_status,      'Show config / view stats for a drop'),
    ('up',         cmd_up,          'Upload clipboard text or a file'),
    ('get',        cmd_get,         'Print clipboard, download file, or fetch URL'),
    ('ls',         cmd_ls,          'List drops, saved items, and folders'),
    ('rm',         cmd_rm,          'Delete a drop'),
    ('mv',         cmd_mv,          'Rename a drop (change its URL key)'),
    ('cp',         cmd_cp,          'Duplicate a drop (server-side copy)'),
    ('renew',      cmd_renew,       'Renew a drop\'s expiry'),
    ('save',       cmd_save,        'Bookmark a drop to your root folder'),
    ('lock',       cmd_lock,        'Set or remove password on a drop'),
    ('mkdir',      cmd_mkdir,       'Create a folder'),
    ('token',      cmd_token,       'Manage API tokens (paid accounts)'),
    ('ask',        cmd_ask,         'Ask the help bot a question about drp'),
    ('getlink',    cmd_getlink,     'Print shareable link (global or --relative)'),
    ('shell',      cmd_shell,       'Interactive shell — ls, cd, cp, mv, rm, and more'),
]

# ── Shared display data ───────────────────────────────────────────────────────
# Single source of truth for command groups and examples.
# Both EPILOG (plain text) and _print_colored_help() render from these.

COMMAND_GROUPS = [
    ('upload / download',  ['up', 'get', 'getlink']),
    ('manage',             ['rm', 'mv', 'cp', 'renew', 'save', 'lock', 'mkdir']),
    ('account',            ['token']),
    ('info',               ['ls', 'status', 'ping']),
    ('help',               ['ask']),
    ('setup',              ['setup', 'login', 'logout']),
    ('shell',              ['shell']),
]

# (command_prefix, argument, description)
EXAMPLES = [
    ('drp up',      '"hello world" -k hello',        'text drop at /hello/'),
    ('echo "hi" |', 'drp up -k hello',               'text from stdin'),
    ('drp up',      'report.pdf -k q3',               'file drop at /q3/'),
    ('drp up',      'report.pdf --expires 30d',       'file with 30-day expiry'),
    ('drp up',      '"secret token" --burn',          'delete after first view'),
    ('drp up',      '"secret" --password pw',         'password-protect (paid)'),
    ('drp up',      'https://example.com/api',        'live API reference'),
    ('drp up',      'https://example.com/f.pdf --remote', 'server-side upload'),
    ('drp get',     'hello',                          'print text to stdout'),
    ('drp get',     'hello --parse',                  'auto-detect format'),
    ('drp get',     'hello --field data.name',        'extract nested value'),
    ('drp get',     'hello.data.name',                'shorthand for --field'),
    ('drp get',     'q3 -o my-report.pdf',            'download with custom name'),
    ('drp get',     'secret --password mypass',       'supply password'),
    ('drp rm',      'notes',                          'delete a drop'),
    ('drp mv',      'notes new-notes',                'rename drop key'),
    ('drp cp',      'notes notes-backup',             'duplicate a drop'),
    ('drp renew',   'notes',                          'renew expiry'),
    ('drp save',    'notes',                          'bookmark to root folder'),
    ('drp lock',    'notes --password pw',            'set password'),
    ('drp mkdir',   'docs',                           'create a folder'),
    ('drp status',  'notes',                          'view count and expiry'),
    ('drp token',   'create --expires 90d',           'create an API key'),
    ('drp ask',     '"how do I upload a file?"',      'ask the help bot'),
    ('drp shell',   '',                               'interactive shell'),
    ('',            '',                               ''),
    ('',            'shell extras:  ls cd cat add',   ''),
    ('',            'open link pwd status clear',     ''),
]


def _build_epilog():
    lines = [
        '',
        'urls:',
        '  /key/      drop page — activity-based or quota-based expiry',
        '  /raw/key/  plain text — for curl | bash workflows',
        '',
        'examples:',
    ]
    col = max(len(f'  {cmd} {arg}') for cmd, arg, _ in EXAMPLES) + 2
    for cmd, arg, desc in EXAMPLES:
        line = f'  {cmd} {arg}'
        lines.append(f'{line:<{col}}{desc}')
    return '\n'.join(lines) + '\n'


EPILOG = _build_epilog()


class _ColorHelpAction(argparse.Action):
    """Intercept -h / --help and fire the colored drp help instead."""

    def __init__(self, option_strings, dest=argparse.SUPPRESS,
                 default=argparse.SUPPRESS, help=None):
        super().__init__(
            option_strings=option_strings,
            dest=dest,
            default=default,
            nargs=0,
            help=help,
        )

    def __call__(self, parser, namespace, values, option_string=None):
        _print_colored_help()
        parser.exit()


def build_parser():
    parser = argparse.ArgumentParser(
        prog='drp',
        description='Drop clipboards and files — get a link instantly.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=EPILOG,
        add_help=False,          # we register our own -h / --help below
    )
    parser.add_argument('-h', '--help', action=_ColorHelpAction,
                        default=argparse.SUPPRESS,
                        help='Show this help message and exit')
    parser.add_argument('--version', '-V', action='version', version=f'%(prog)s {__version__}')
    sub = parser.add_subparsers(dest='command')
    for name, _, help_str in COMMANDS:
        sub.add_parser(name, help=help_str)
    _configure_subparsers(sub)
    return parser


def _configure_subparsers(sub):
    try:
        from cli.completion import key_completer
        _completers = {'key': key_completer}
    except Exception:
        _completers = {}

    def _attach(arg, kind):
        if kind in _completers:
            arg.completer = _completers[kind]

    # ── up ────────────────────────────────────────────────────────────────────
    p_up = sub._name_parser_map['up']
    p_up.add_argument('target', nargs='?', default=None,
                      help='File path, text string, or https:// URL (omit to read stdin)')
    p_up.add_argument('-f', '--file', action='store_true',
                      help='Force upload as a file drop (e.g. when piping binary data)')
    p_up.add_argument('-c', '--clip', action='store_true',
                      help='Force upload as clipboard text')
    p_up.add_argument('--key', '-k', default=None)
    p_up.add_argument('--expires', '-e', default=None, metavar='DURATION',
                      help='7d, 30d, 1y (paid accounts only)')
    p_up.add_argument('--burn', '-b', action='store_true',
                      help='Delete after first view (all plans)')
    p_up.add_argument('--password', '-p', default=None, nargs='?', const='__prompt__',
                      metavar='PASSWORD',
                      help='Password-protect this drop (prompted if omitted; paid accounts only)')
    p_up.add_argument('--schedule', default=None, metavar='DURATION',
                      help='Schedule drop visibility: 2h, 30m, 1d (paid)')
    p_up.add_argument('--webhook', default=None, metavar='URL',
                      help='POST to URL on access (paid)')
    p_up.add_argument('--notify', default=None, metavar='DURATION',
                      help='Email before expiry: 7d, 24h (paid)')
    p_up.add_argument('--template', default=None, metavar='SLUG',
                      help='Use a drop template')
    p_up.add_argument('--alias', default=None, metavar='NAME',
                      help='Create alias after upload: @handle/alias → drop')
    p_up.add_argument('--public', action='store_true', default=False,
                      help='Make drop visible in public feed')
    p_up.add_argument('--tag', default=None, metavar='TAGS',
                      help='Comma-separated tags for public discovery')
    p_up.add_argument('--remote', action='store_true', default=False,
                      help='Upload URL server-side (server fetches the file; Pro plan)')

    # ── get ───────────────────────────────────────────────────────────────────
    p_get = sub._name_parser_map['get']
    _attach(p_get.add_argument('key'), 'key')
    p_get.add_argument('--output', '-o', default=None)
    p_get.add_argument('--url', '-u', action='store_true')
    p_get.add_argument('--timing', action='store_true')
    p_get.add_argument('--parse', action='store_true',
                       help='Auto-detect content format and print parsed output')
    p_get.add_argument('--field', default=None, metavar='PATH',
                       help='Extract a nested field via dot-path (e.g. data.items.0.name)')
    p_get.add_argument('--password', '-p', default=None, nargs='?', const='__prompt__',
                       metavar='PASSWORD',
                       help='Password for a protected drop (prompted if omitted)')

    # ── status ────────────────────────────────────────────────────────────────
    p_status = sub._name_parser_map['status']
    _attach(p_status.add_argument('key', nargs='?', default=None), 'key')

    # ── token ─────────────────────────────────────────────────────────────────
    p_token = sub._name_parser_map['token']
    tok_sub = p_token.add_subparsers(dest='token_action')
    p_tok_create = tok_sub.add_parser('create', help='Create an API token')
    p_tok_create.add_argument('--expires', '-e', default=None, metavar='DURATION',
                              help='90d, 24h, 365d')
    p_tok_create.add_argument('--label', '-l', default=None,
                              help='Label for identification')
    tok_sub.add_parser('list', help='List API tokens')
    p_tok_revoke = tok_sub.add_parser('revoke', help='Revoke an API token')
    p_tok_revoke.add_argument('token_id', type=int, help='Token ID (from drp token list)')

    # ── getlink ────────────────────────────────────────────────────────────────
    p_gl = sub._name_parser_map['getlink']
    _attach(p_gl.add_argument('key'), 'key')
    p_gl.add_argument('--relative', '-r', action='store_true',
                      help='Print folder-path link (/@user/folder/file) instead of /key/')

    # ── ask ───────────────────────────────────────────────────────────────────
    p_ask = sub._name_parser_map['ask']
    p_ask.add_argument('question', nargs='?', default=None,
                       help='Question to ask (prompted if omitted)')
    p_ask.add_argument('--history', action='store_true',
                       help='View help bot conversation history')
    p_ask.add_argument('--clear', action='store_true',
                       help='Clear help bot conversation history')

    # ── login ─────────────────────────────────────────────────────────────────
    p_login = sub._name_parser_map['login']
    p_login.add_argument('--token', '-t', default=None, metavar='TOKEN',
                         help='Log in with an API token instead of password')

    # ── rm ────────────────────────────────────────────────────────────────────
    p_rm = sub._name_parser_map['rm']
    _attach(p_rm.add_argument('key'), 'key')

    # ── mv ────────────────────────────────────────────────────────────────────
    p_mv = sub._name_parser_map['mv']
    _attach(p_mv.add_argument('key'), 'key')
    p_mv.add_argument('new_key', help='New drop key')

    # ── cp ────────────────────────────────────────────────────────────────────
    p_cp = sub._name_parser_map['cp']
    _attach(p_cp.add_argument('key'), 'key')
    p_cp.add_argument('new_key', nargs='?', default=None,
                      help='Key for the copy (auto-generated if omitted)')

    # ── renew ─────────────────────────────────────────────────────────────────
    p_renew = sub._name_parser_map['renew']
    _attach(p_renew.add_argument('key'), 'key')

    # ── save ──────────────────────────────────────────────────────────────────
    p_save = sub._name_parser_map['save']
    _attach(p_save.add_argument('key'), 'key')

    # ── lock ──────────────────────────────────────────────────────────────────
    p_lock = sub._name_parser_map['lock']
    _attach(p_lock.add_argument('key'), 'key')
    p_lock.add_argument('--password', '-p', default=None, nargs='?', const='__prompt__',
                        metavar='PASSWORD',
                        help='Password to set (prompted if omitted)')
    p_lock.add_argument('--remove', '-r', action='store_true',
                        help='Remove password instead of setting one')

    # ── mkdir ─────────────────────────────────────────────────────────────────
    p_mkdir = sub._name_parser_map['mkdir']
    p_mkdir.add_argument('name', help='Folder name')
    p_mkdir.add_argument('--parent', default=None, metavar='SLUG',
                         help='Parent folder slug (creates nested folder)')
    # ── ls ────────────────────────────────────────────────────────────────────
    p_ls = sub._name_parser_map['ls']
    p_ls.add_argument('-l', '--long', action='store_true',
                      help='Long format with size, time, expiry')
    p_ls.add_argument('--bytes', action='store_true',
                      help='Show raw byte counts instead of human-readable')
    p_ls.add_argument('--col', action='store_true',
                      help='Show folders instead of drops')
    p_ls.add_argument('-t', '--type', default=None, choices=['text', 'file', 's'],
                      help='Filter: text, file, or s (saved)')
    p_ls.add_argument('-s', '--sort', default=None, choices=['name', 'size', 'time'],
                      help='Sort by name, size, or time')
    p_ls.add_argument('--reverse', '-r', action='store_true',
                      help='Reverse sort order')
    p_ls.add_argument('--export', action='store_true',
                      help='Export as JSON')

_HANDLERS = {name: handler for name, handler, _ in COMMANDS}


def _print_colored_help():
    from cli.format import bold, dim, cyan, green

    print(f'  {bold("drp")} {dim(__version__)}  — drop clipboards and files, get a link instantly.')
    print()
    print(f'  {dim("usage:")}  drp <command> [options]')
    print()

    # ── Commands ──────────────────────────────────────────────────────────────
    print(f'  {dim("commands:")}')
    cmd_map = {name: help_str for name, _, help_str in COMMANDS}
    for group_label, names in COMMAND_GROUPS:
        print(f'    {dim(group_label)}')
        for name in names:
            print(f'      {cyan(f"drp {name:<10}")}  {cmd_map.get(name, "")}')
        print()

    # ── URLs ───────────────────────────────────────────────────────────────────
    print(f'  {dim("urls:")}')
    print(f'    {green("/key/")}      drop page')
    print(f'    {green("/raw/key/")}  plain text — for curl | bash workflows')
    print()

    # ── Examples — same data as EPILOG ────────────────────────────────────────
    print(f'  {dim("examples:")}')
    col = max(len(f'    {cmd} {arg}') for cmd, arg, _ in EXAMPLES) + 2
    for cmd, arg, desc in EXAMPLES:
        raw_len = len(f'    {cmd} {arg}')
        padding = ' ' * (col - raw_len)
        print(f'    {dim(cmd)} {arg}{padding}{dim(desc)}')
    print()

    print(f'  {dim("drp <command> --help for per-command options.")}')

def main():
    parser = build_parser()
    try:
        import argcomplete
        argcomplete.autocomplete(parser)
    except ImportError:
        pass
    args = parser.parse_args()
    if args.command is None:
        _print_colored_help()
        return

    # Fire-and-forget background version check (never blocks the command)
    from cli.version_check import start_check, show_notice
    checker = start_check()

    if args.command in _HANDLERS:
        try:
            _HANDLERS[args.command](args)
        except KeyboardInterrupt:
            pass
        except SystemExit:
            raise
        except Exception as exc:
            from cli.crash_reporter import report
            report(args.command, exc)
            print(f'\n  ✗ Unexpected error: {type(exc).__name__}: {exc}')
            print('    This has been reported automatically.')
            sys.exit(1)
    else:
        parser.print_help()

    # Show upgrade notice (if the thread finished and a newer version exists)
    show_notice(checker)


if __name__ == '__main__':
    main()