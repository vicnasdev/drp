"""
drp edit — open a clipboard drop in $EDITOR, re-upload on save.

  drp edit <key>

Fetches the drop content, opens it in $EDITOR (falls back to nano, then vi),
and re-uploads if the content changed. No-ops if nothing changed.
File drops are not supported — editing binary files makes no sense.
"""

import os
import subprocess
import sys
import tempfile

from cli import api
from cli.commands._context import load_context


def cmd_edit(args):
    cfg, host, session = load_context()

    # ── Fetch current content ─────────────────────────────────────────────────
    from cli.spinner import Spinner
    with Spinner('fetching'):
        kind, content = api.get_clipboard(host, session, args.key)

    if kind is None:
        try:
            res = session.get(
                f'{host}/f/{args.key}/',
                headers={'Accept': 'application/json'},
                timeout=10,
            )
            if res.ok and res.json().get('kind') == 'file':
                print(f'  ✗ /{args.key}/ is a file drop — drp edit only works on clipboard drops.')
                sys.exit(1)
        except Exception:
            pass
        print(f'  ✗ Drop /{args.key}/ not found.')
        sys.exit(1)

    # ── Open in editor ────────────────────────────────────────────────────────
    editor = (
        os.environ.get('VISUAL')
        or os.environ.get('EDITOR')
        or _find_editor()
    )

    with tempfile.NamedTemporaryFile(
        mode='w', suffix='.txt', prefix=f'drp-{args.key}-',
        delete=False, encoding='utf-8',
    ) as f:
        f.write(content)
        tmp_path = f.name

    try:
        result = subprocess.run([editor, tmp_path])
        if result.returncode != 0:
            print(f'  ✗ Editor exited with code {result.returncode}.')
            sys.exit(1)

        with open(tmp_path, encoding='utf-8') as f:
            new_content = f.read()
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    # ── Re-upload if changed ──────────────────────────────────────────────────
    if new_content == content:
        print('  (no changes)')
        return

    result_key = api.upload_text(host, session, new_content, key=args.key)
    if result_key:
        print(f'  ✓ /{result_key}/ updated')
    else:
        print(f'  ✗ Upload failed.')
        sys.exit(1)


def _find_editor():
    for editor in ('nano', 'vi', 'notepad'):
        if _on_path(editor):
            return editor
    return 'vi'


def _on_path(name):
    import shutil
    return shutil.which(name) is not None
