"""
Public API surface for the drp CLI.
Import from here to keep command modules clean.
"""

from .auth import get_csrf, login
from .text import upload_text, get_clipboard
from .file import upload_file, get_file, upload_from_url
from .actions import (
    delete, rename, renew, list_drops, key_exists, save_bookmark,
    copy_drop, lock_drop, create_folder,
)
from .helpers import slug, err, ok

__all__ = [
    'get_csrf', 'login',
    'upload_text', 'get_clipboard',
    'upload_file', 'get_file', 'upload_from_url',
    'delete', 'rename', 'renew', 'list_drops', 'key_exists', 'save_bookmark',
    'copy_drop', 'lock_drop', 'create_folder',
    'slug', 'err', 'ok',
]