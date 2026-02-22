from functools import cache
from pathlib import Path

from django.shortcuts import render


def index(request):
    return render(request, 'help/index.html', {
        'readme_html': _get_readme_html(),
    })


def cli(request):
    return render(request, 'help/cli.html', {
        'parser_info': _get_parser_info(),
    })


def expiry(request):
    return render(request, 'help/expiry.html')


def plans(request):
    from core.models import PlanLimit, Plan
    limits = PlanLimit.all_as_dicts()
    # Ensure consistent order: anon, free, starter, pro
    ordered = [
        (Plan.ANON,    limits.get(Plan.ANON,    {})),
        (Plan.FREE,    limits.get(Plan.FREE,    {})),
        (Plan.STARTER, limits.get(Plan.STARTER, {})),
        (Plan.PRO,     limits.get(Plan.PRO,     {})),
    ]
    return render(request, 'help/plans.html', {'plans': ordered})


@cache
def _get_readme_html():
    import markdown
    readme_path = Path(__file__).resolve().parent.parent / 'README.md'
    text = readme_path.read_text()
    html = markdown.markdown(text, extensions=['tables', 'fenced_code'])
    html = html.replace('href="LICENSE"', 'href="https://github.com/vicnasdev/drp/blob/main/LICENSE"')
    return html


@cache
def _get_parser_info():
    import argparse
    from cli.drp import build_parser, COMMANDS

    parser = build_parser()

    # Locate the subparser map from argparse internals
    sub_map = {}
    for action in parser._subparsers._group_actions:
        if hasattr(action, '_name_parser_map'):
            sub_map = action._name_parser_map
            break

    commands = []
    for name, _, help_str in COMMANDS:
        sub = sub_map.get(name)
        args = []

        if sub:
            for action in sub._actions:
                # Skip the default --help action
                if isinstance(action, argparse._HelpAction):
                    continue

                # Positional arguments
                if not action.option_strings:
                    args.append({
                        'flags': action.dest,
                        'help': action.help or '',
                        'required': action.required if hasattr(action, 'required') else True,
                        'default': None,
                        'metavar': (action.metavar or action.dest).upper(),
                        'positional': True,
                        'is_flag': False,
                    })
                else:
                    # Optional flags
                    is_flag = isinstance(action, argparse._StoreTrueAction) or \
                              isinstance(action, argparse._StoreFalseAction)
                    metavar = ''
                    if not is_flag:
                        metavar = action.metavar or (
                            action.dest.upper() if action.dest else ''
                        )
                    args.append({
                        'flags': ', '.join(action.option_strings),
                        'help': action.help or '',
                        'required': action.required if hasattr(action, 'required') else False,
                        'default': action.default if action.default not in (None, argparse.SUPPRESS) else None,
                        'metavar': metavar,
                        'positional': False,
                        'is_flag': is_flag,
                    })

        commands.append({
            'name': name,
            'help': help_str,
            'args': args,
            'epilog': (sub.epilog or '').strip() if sub else '',
        })

    return {
        'description': parser.description,
        'epilog': (parser.epilog or '').strip(),
        'commands': commands,
    }