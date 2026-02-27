"""
drp getlink — print the shareable link for a drop.

  drp getlink <key>              print the global link (/key/)
  drp getlink <key> --relative   print the folder-path link (/@user/folder/file)
"""

from cli.commands._context import load_context
from cli.format import cyan, dim, red


def cmd_getlink(args):
    cfg, host, session = load_context()
    key = args.key

    if getattr(args, 'relative', False):
        # Fetch drop JSON to get folder_path
        try:
            res = session.get(
                f'{host}/{key}/',
                headers={'Accept': 'application/json'},
                timeout=10,
            )
        except Exception as e:
            print(f'  {red("✗")} {e}')
            return

        if not res.ok:
            print(f'  {red("✗")} {res.status_code}: drop not found.')
            return

        data = res.json()
        folder_path = data.get('folder_path')
        if not folder_path:
            print(f'  {red("✗")} drop is not in any folder — no relative link available.')
            return

        url = f'{host}{folder_path}'
        print(f'  {cyan(url)}')
    else:
        url = f'{host}/{key}/'
        print(f'  {cyan(url)}')
