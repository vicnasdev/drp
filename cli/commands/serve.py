"""
drp serve — upload a directory (or glob) and print a URL table.

  drp serve ./dist/             upload all files in dist/
  drp serve ./dist/ --expires 7d
  drp serve "*.log"             upload matching files (quoted glob)
  drp serve report.pdf notes.txt  upload specific files

Each file is uploaded as a file drop. Keys are derived from filenames
(slugified). Already-taken keys get a short random suffix.
Respects plan file size and storage quota limits — skips files that
would exceed them and reports which ones were skipped.
"""

import glob
import os
import sys

from cli import api, config
from cli.commands._context import load_context
from cli.commands.upload import _parse_expires
from cli.crash_reporter import report_outcome


def cmd_serve(args):
    cfg, host, session = load_context(require_login=True)

    paths = _resolve_paths(args.targets)
    if not paths:
        print('  ✗ No files found.')
        sys.exit(1)

    expiry_days = _parse_expires(getattr(args, 'expires', None))

    from cli.format import green, red, dim, bold

    col_w    = max(len(os.path.basename(p)) for p in paths) + 2
    uploaded = []
    skipped  = []

    print(f'  {bold("drp serve")}  uploading {len(paths)} file(s)\n')

    for path in paths:
        filename = os.path.basename(path)
        key = api.slug(filename)

        from cli.api.actions import key_exists
        import secrets
        if key_exists(host, session, key, ns='f'):
            key = f'{key}-{secrets.token_urlsafe(4)}'

        try:
            result_key = api.upload_file(
                host, session, path, key=key, expiry_days=expiry_days
            )
        except Exception as e:
            print(f'  {red("✗")} {filename:<{col_w}}  error: {e}')
            skipped.append(filename)
            continue

        if not result_key:
            print(f'  {red("✗")} {filename:<{col_w}}  upload failed (quota or size limit?)')
            skipped.append(filename)
            continue

        url = f'{host}/f/{result_key}/'
        print(f'  {green("✓")} {filename:<{col_w}}  {url}')
        uploaded.append((filename, url))
        config.record_drop(result_key, 'file', ns='f', filename=filename, host=host)

    print()
    print(f'  {dim(str(len(uploaded)))} uploaded', end='')
    if skipped:
        print(f'  ·  {red(str(len(skipped)))} skipped', end='')
    print()


def _resolve_paths(targets):
    """
    Expand targets to a deduplicated list of file paths.
    Each target can be a file path, directory, or glob pattern.
    """
    seen   = set()
    result = []

    for target in targets:
        if os.path.isdir(target):
            for entry in sorted(os.listdir(target)):
                full = os.path.join(target, entry)
                if os.path.isfile(full) and full not in seen:
                    seen.add(full)
                    result.append(full)
        elif os.path.isfile(target):
            if target not in seen:
                seen.add(target)
                result.append(target)
        else:
            for full in sorted(glob.glob(target)):
                if os.path.isfile(full) and full not in seen:
                    seen.add(full)
                    result.append(full)

    return result
