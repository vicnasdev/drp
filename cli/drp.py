#!/usr/bin/env python3
"""drp — drop clipboards and files from the command line. Run `drp --help`."""

import argparse
import sys

from cli import __version__
from cli.commands.setup import cmd_setup, cmd_login, cmd_logout
from cli.commands.upload import cmd_up
from cli.commands.get import cmd_get
from cli.commands.manage import cmd_rm, cmd_mv, cmd_renew
from cli.commands.save import cmd_save
from cli.commands.ls import cmd_ls
from cli.commands.load import cmd_load
from cli.commands.status import cmd_status, cmd_ping
from cli.commands.edit import cmd_edit
from cli.commands.cp import cmd_cp
from cli.commands.serve import cmd_serve
from cli.commands.shell import cmd_shell
from cli.commands.collection import cmd_collection
from cli.commands.token import cmd_token
from cli.commands.ask import cmd_ask
from cli.commands.cache import cmd_cache, cmd_rmcache
from cli.commands.send import cmd_send, cmd_claim

COMMANDS = [
    ('setup',      cmd_setup,       'Configure host and log in'),
    ('login',      cmd_login,       'Log in (session saved — no repeated prompts)'),
    ('logout',     cmd_logout,      'Log out and clear saved session'),
    ('ping',       cmd_ping,        'Check connectivity to the drp server'),
    ('status',     cmd_status,      'Show config / view stats for a drop'),
    ('up',         cmd_up,          'Upload clipboard text or a file'),
    ('get',        cmd_get,         'Print clipboard, download file, or fetch URL'),
    ('edit',       cmd_edit,        'Open a clipboard drop in $EDITOR and re-upload'),
    ('cp',         cmd_cp,          'Duplicate a drop under a new key'),
    ('save',       cmd_save,        'Bookmark a drop to your account (requires login)'),
    ('rm',         cmd_rm,          'Delete a drop'),
    ('mv',         cmd_mv,          'Rename a key (blocked 24h after creation)'),
    ('renew',      cmd_renew,       'Renew expiry (paid accounts only)'),
    ('ls',         cmd_ls,          'List your drops'),
    ('load',       cmd_load,        'Import a shared export as saved drops (requires login)'),
    ('serve',      cmd_serve,       'Upload a directory or file list, print URL table'),
    ('collection', cmd_collection,  'Manage drop collections (paid accounts)'),
    ('token',      cmd_token,       'Manage API tokens (paid accounts)'),
    ('ask',        cmd_ask,         'Ask the help bot a question about drp'),
    ('send',       cmd_send,        'Transfer drop ownership via one-time token'),
    ('claim',      cmd_claim,       'Claim a drop sent to you'),
    ('cache',      cmd_cache,       'View the local drop cache'),
    ('rmcache',    cmd_rmcache,     'Remove entries from the local drop cache'),
    ('shell',      cmd_shell,       'Interactive shell with ls, rm, cp, cd and more'),
]

# ── Shared display data ───────────────────────────────────────────────────────
# Single source of truth for command groups and examples.
# Both EPILOG (plain text) and _print_colored_help() render from these.

COMMAND_GROUPS = [
    ('upload / download',  ['up', 'get', 'edit', 'serve']),
    ('manage',             ['rm', 'mv', 'cp', 'renew', 'send', 'claim']),
    ('account',            ['save', 'ls', 'load', 'collection', 'token']),
    ('info',               ['status', 'ping']),
    ('help',               ['ask']),
    ('cache',              ['cache', 'rmcache']),
    ('setup',              ['setup', 'login', 'logout']),
    ('shell',              ['shell']),
]

# (command_prefix, argument, description)
EXAMPLES = [
    ('drp up',      '"hello world" -k hello',        'clipboard at /hello/'),
    ('echo "hi" |', 'drp up -k hello',               'clipboard from stdin'),
    ('drp up',      'report.pdf -k q3',               'file at /f/q3/'),
    ('drp up',      'report.pdf --expires 30d',       'file with 30-day expiry'),
    ('drp up',      '"secret token" --burn',          'delete after first view'),
    ('drp up',      '"secret" --password pw',         'password-protect (paid)'),
    ('drp up',      'https://example.com/api',        'live API reference (fresh on each get)'),
    ('drp get',     'hello',                          'print clipboard to stdout'),
    ('drp get',     'hello --parse',                  'auto-detect format (JSON, CSV, …)'),
    ('drp get',     'hello --field data.name',        'extract nested value from JSON/XML'),
    ('drp get',     'hello.data.name',                'shorthand for --field'),
    ('drp get',     'https://api.example.com/data',   'fetch external URL (paid plans)'),
    ('drp get',     'hello --url',                    'print URL without fetching'),
    ('drp get',     '-f q3 -o my-report.pdf',         'download file with custom name'),
    ('drp get',     'secret --password mypass',       'supply password for protected drop'),
    ('drp edit',    'notes',                          'open in $EDITOR, re-upload on save'),
    ('drp cp',      'notes notes-backup',             'duplicate clipboard drop'),
    ('drp cp',      '-f q3 q3-backup',               'duplicate file drop (server-side)'),
    ('drp serve',   './dist/',                        'upload all files in dir, print URLs'),
    ('drp serve',   '"*.log" --expires 7d',           'upload glob with expiry'),
    ('drp status',  'notes',                          'view count and last seen for a drop'),
    ('drp save',    'notes',                          'bookmark clipboard (appears in drp ls)'),
    ('drp save',    '-f report',                      'bookmark file'),
    ('drp rm',      'hello',                          'delete clipboard'),
    ('drp rm',      '-f report',                      'delete file'),
    ('drp mv',      'q3 quarter3',                    'rename clipboard key'),
    ('drp mv',      '-f q3 quarter3',                'rename file key'),
    ('drp ls',      '-l',                             'list with sizes and times'),
    ('drp ls',      '--col',                          'list your collections'),
    ('drp ls',      '--export > backup.json',         'export as JSON'),
    ('drp load',    'backup.json',                    'import shared export as saved drops'),
    ('drp collection', 'ls',                          'list collections'),
    ('drp collection', 'new "my notes"',              'create a collection'),
    ('drp collection', 'add my-notes key',            'add drop to collection'),
    ('drp shell',   '',                               'interactive shell (ls, rm, cd, …)'),
    ('drp send',    'mykey',                          'generate transfer token'),
    ('drp claim',   '<token>',                        'claim a drop sent to you'),
    ('drp ask',     '"how do I upload a file?"',        'ask the help bot'),
    ('drp token',   'create --expires 90d',            'create an API key'),
    ('',            'DRP_API_KEY=xxx drp up file.py',  'upload with API key (no login)'),]


def _build_epilog():
    lines = [
        '',
        'urls:',
        '  /key/      clipboard — activity-based expiry',
        '  /f/key/    file — expires after upload (anon) or by quota (paid)',
        '  /raw/key/  clipboard as plain text — for curl | bash workflows',
        '',
        'key format:',
        '  key        clipboard (default)',
        '  -f key     file drop',
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
    # login --token
    p_login = sub._name_parser_map['login']
    p_login.add_argument('--token', '-t', default=None, metavar='TOKEN',
                         help='Log in with an API token instead of password')
    _configure_subparsers(sub)
    return parser


def _configure_subparsers(sub):
    try:
        from cli.completion import (
            key_completer, file_key_completer, clipboard_key_completer,
            collection_slug_completer,
        )
        _completers = {
            'key':              key_completer,
            'file_key':         file_key_completer,
            'clip_key':         clipboard_key_completer,
            'collection_slug':  collection_slug_completer,
        }
    except Exception:
        _completers = {}

    def _attach(arg, kind):
        if kind in _completers:
            arg.completer = _completers[kind]

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

    p_get = sub._name_parser_map['get']
    p_get.add_argument('-f', '--file', action='store_true')
    p_get.add_argument('-c', '--clip', action='store_true')
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

    p_edit = sub._name_parser_map['edit']
    _attach(p_edit.add_argument('key'), 'clip_key')

    p_cp = sub._name_parser_map['cp']
    p_cp.add_argument('-f', '--file', action='store_true')
    p_cp.add_argument('-c', '--clip', action='store_true')
    _attach(p_cp.add_argument('key', help='Source key'), 'key')
    p_cp.add_argument('new_key')

    p_rm = sub._name_parser_map['rm']
    p_rm.add_argument('-f', '--file', action='store_true')
    p_rm.add_argument('-c', '--clip', action='store_true')
    _attach(p_rm.add_argument('key'), 'key')

    p_mv = sub._name_parser_map['mv']
    p_mv.add_argument('-f', '--file', action='store_true')
    p_mv.add_argument('-c', '--clip', action='store_true')
    _attach(p_mv.add_argument('key', help='Current key'), 'key')
    p_mv.add_argument('new_key')

    p_renew = sub._name_parser_map['renew']
    p_renew.add_argument('-f', '--file', action='store_true')
    p_renew.add_argument('-c', '--clip', action='store_true')
    _attach(p_renew.add_argument('key'), 'key')

    p_save = sub._name_parser_map['save']
    p_save.add_argument('-f', '--file', action='store_true')
    p_save.add_argument('-c', '--clip', action='store_true')
    _attach(p_save.add_argument('key'), 'key')

    p_status = sub._name_parser_map['status']
    p_status.add_argument('key', nargs='?', default=None)
    p_status.add_argument('-f', '--file', action='store_true')
    p_status.add_argument('-c', '--clip', action='store_true')

    p_ls = sub._name_parser_map['ls']
    p_ls.add_argument('-l', '--long', action='store_true')
    p_ls.add_argument('--bytes', action='store_true')
    p_ls.add_argument('-t', '--type', choices=['c', 'f', 's'], default=None, metavar='TYPE')
    p_ls.add_argument('--sort', choices=['time', 'size', 'name'], default=None)
    p_ls.add_argument('-r', '--reverse', action='store_true')
    p_ls.add_argument('--export', action='store_true')
    p_ls.add_argument('--col', action='store_true', help='List collections instead of drops')

    p_load = sub._name_parser_map['load']
    p_load.add_argument('file')

    p_serve = sub._name_parser_map['serve']
    p_serve.add_argument('targets', nargs='+',
                         help='Files, directories, or glob patterns')
    p_serve.add_argument('--expires', '-e', default=None, metavar='DURATION',
                         help='7d, 30d, 1y (paid only)')

    # collection subcommand
    p_col = sub._name_parser_map['collection']
    col_sub = p_col.add_subparsers(dest='col_cmd')
    col_sub.add_parser('ls',   help='List collections')
    p_col_new = col_sub.add_parser('new',  help='Create a collection')
    p_col_new.add_argument('name_parts', nargs='+', metavar='NAME')
    p_col_new.add_argument('--parent', '-p', default=None, metavar='SLUG',
                           help='Parent collection slug/path for nesting')
    p_col_add = col_sub.add_parser('add',  help='Add drop to collection')
    _attach(p_col_add.add_argument('slug'), 'collection_slug')
    _attach(p_col_add.add_argument('key'),  'key')
    p_col_add.add_argument('-f', '--file', action='store_true')
    p_col_rm  = col_sub.add_parser('rm',   help='Remove drop from collection')
    _attach(p_col_rm.add_argument('slug'), 'collection_slug')
    _attach(p_col_rm.add_argument('key'),  'key')
    p_col_rm.add_argument('-f', '--file', action='store_true')
    p_col_open = col_sub.add_parser('open', help='Print collection URL')
    _attach(p_col_open.add_argument('slug'), 'collection_slug')

    # token subcommand
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

    # ask subcommand
    p_ask = sub._name_parser_map['ask']
    p_ask.add_argument('question', nargs='?', default=None,
                       help='Question to ask (prompted if omitted)')

    # rmcache subcommand
    p_rmcache = sub._name_parser_map['rmcache']
    p_rmcache.add_argument('key', nargs='?', default=None,
                           help='Drop key to remove from cache')
    p_rmcache.add_argument('--all', '-a', action='store_true',
                           help='Clear the entire cache')

    # send subcommand
    p_send = sub._name_parser_map['send']
    p_send.add_argument('-f', '--file', action='store_true')
    p_send.add_argument('-c', '--clip', action='store_true')
    _attach(p_send.add_argument('key'), 'key')

    # claim subcommand
    p_claim = sub._name_parser_map['claim']
    p_claim.add_argument('token', help='Transfer token from drp send')


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

    # ── Key format ────────────────────────────────────────────────────────────
    print(f'  {dim("key format:")}')
    print(f'    {green("key")}       clipboard  →  /key/')
    print(f'    {green("-f key")}    file       →  /f/key/')
    print(f'    {dim("raw url")}    plain text →  /raw/key/')
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


if __name__ == '__main__':
    main()