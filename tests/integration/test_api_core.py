"""
tests/integration/test_api_core.py

Core API integration tests: text drop CRUD, file drop CRUD,
access control (locked drops), saved bookmarks, drop actions (rename, delete, copy).
"""

import os
import tempfile
import pytest

from conftest import HOST, unique_key
from cli.api.text import upload_text, get_clipboard
from cli.api.file import upload_file, get_file
from cli.api.actions import delete, rename, save_bookmark


def _tmp(content=b'data', suffix='.bin'):
    f = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    f.write(content); f.close()
    return f.name


# ── Text drops ────────────────────────────────────────────────────────────────

class TestTextDrops:
    def test_anon_upload_and_fetch(self, anon):
        key = unique_key('txt-anon')
        result = upload_text(HOST, anon, 'hello world', key=key, is_test=True)
        assert result == key
        kind, content = get_clipboard(HOST, anon, key)
        assert kind == 'text' and content == 'hello world'

    def test_free_upload_and_fetch(self, free_user, anon):
        key = free_user.track(unique_key('txt-free'))
        upload_text(HOST, free_user.session, 'free content', key=key, is_test=True)
        kind, content = get_clipboard(HOST, anon, key)
        assert kind == 'text' and content == 'free content'

    def test_overwrite_updates_content(self, free_user, anon):
        key = unique_key('txt-overwrite')
        upload_text(HOST, anon, 'v1', key=key, is_test=True)
        upload_text(HOST, anon, 'v2', key=key, is_test=True)
        _, content = get_clipboard(HOST, anon, key)
        assert content == 'v2'

    def test_drop_not_found_returns_none(self, anon):
        kind, content = get_clipboard(HOST, anon, 'drptest-no-such-key-xyz')
        assert kind is None


# ── File drops ────────────────────────────────────────────────────────────────

class TestFileDrops:
    def test_free_upload_and_download(self, free_user, anon):
        path = _tmp(b'file content here')
        key  = free_user.track(unique_key('file-free'), ns='f')
        try:
            result = upload_file(HOST, free_user.session, path, key=key, is_test=True)
        finally:
            os.unlink(path)
        assert result is not None
        kind, data = get_file(HOST, anon, key)
        assert kind == 'file' and data is not None

    def test_anon_file_upload(self, anon):
        path = _tmp(b'anon file')
        key  = unique_key('file-anon')
        try:
            result = upload_file(HOST, anon, path, key=key, is_test=True)
        finally:
            os.unlink(path)
        assert result is not None


# ── Access control ────────────────────────────────────────────────────────────

class TestAccessControl:
    def test_other_cannot_overwrite_paid_drop(self, starter_user, free_user):
        key = starter_user.track(unique_key('ac-lock'))
        upload_text(HOST, starter_user.session, 'owner content', key=key, is_test=True)
        # free_user tries to overwrite — should fail
        import requests as req_lib
        s = req_lib.Session()
        from cli.api.auth import get_csrf
        csrf = get_csrf(HOST, free_user.session)
        res = free_user.session.post(
            f'{HOST}/save/',
            data={'key': key, 'content': 'hijack', 'csrfmiddlewaretoken': csrf},
            headers={'Accept': 'application/json'},
        )
        assert res.status_code == 403

    def test_owner_can_overwrite_own_drop(self, starter_user):
        key = starter_user.track(unique_key('ac-own'))
        upload_text(HOST, starter_user.session, 'v1', key=key, is_test=True)
        result = upload_text(HOST, starter_user.session, 'v2', key=key, is_test=True)
        assert result is not None
        _, content = get_clipboard(HOST, starter_user.session, key)
        assert content == 'v2'


# ── Rename & delete ───────────────────────────────────────────────────────────

class TestRenameDelete:
    def test_rename_clipboard_drop(self, free_user):
        key     = unique_key('mv-src')
        new_key = unique_key('mv-dst')
        upload_text(HOST, free_user.session, 'rename me', key=key, is_test=True)
        result = rename(HOST, free_user.session, key, new_key, ns='c')
        assert result == new_key

    def test_delete_clipboard_drop(self, free_user, anon):
        key = unique_key('del-txt')
        upload_text(HOST, free_user.session, 'bye', key=key, is_test=True)
        ok = delete(HOST, free_user.session, key, ns='c')
        assert ok
        kind, _ = get_clipboard(HOST, anon, key)
        assert kind is None

    def test_rename_to_taken_key_fails(self, free_user):
        key1 = unique_key('mv-taken1')
        key2 = unique_key('mv-taken2')
        upload_text(HOST, free_user.session, 'a', key=key1, is_test=True)
        upload_text(HOST, free_user.session, 'b', key=key2, is_test=True)
        result = rename(HOST, free_user.session, key1, key2, ns='c')
        assert result is False


# ── Copy ──────────────────────────────────────────────────────────────────────

class TestCopy:
    def test_copy_produces_new_drop(self, free_user, anon):
        from cli.api.auth import get_csrf
        key     = unique_key('cp-orig')
        new_key = unique_key('cp-copy')
        upload_text(HOST, free_user.session, 'original', key=key, is_test=True)
        csrf = get_csrf(HOST, free_user.session)
        res = free_user.session.post(
            f'{HOST}/{key}/copy/',
            json={'new_key': new_key},
            headers={'X-CSRFToken': csrf, 'Content-Type': 'application/json'},
        )
        assert res.ok
        kind, content = get_clipboard(HOST, anon, new_key)
        assert kind == 'text' and content == 'original'

    def test_copy_to_taken_key_returns_409(self, free_user):
        from cli.api.auth import get_csrf
        key1 = unique_key('cp-409a')
        key2 = unique_key('cp-409b')
        upload_text(HOST, free_user.session, 'a', key=key1, is_test=True)
        upload_text(HOST, free_user.session, 'b', key=key2, is_test=True)
        csrf = get_csrf(HOST, free_user.session)
        res = free_user.session.post(
            f'{HOST}/{key1}/copy/',
            json={'new_key': key2},
            headers={'X-CSRFToken': csrf, 'Content-Type': 'application/json'},
        )
        assert res.status_code == 409


# ── Bookmarks ─────────────────────────────────────────────────────────────────

class TestBookmarks:
    def test_logged_in_user_can_save_bookmark(self, free_user):
        key = unique_key('bk-save')
        upload_text(HOST, free_user.session, 'bookmark me', key=key, is_test=True)
        ok = save_bookmark(HOST, free_user.session, key, ns='c')
        assert ok

    def test_anon_cannot_save_bookmark(self, anon):
        key = unique_key('bk-anon')
        upload_text(HOST, anon, 'anon content', key=key, is_test=True)
        ok = save_bookmark(HOST, anon, key, ns='c')
        assert not ok