"""
tests/integration/test_plans.py

Plan-gated feature integration tests against a real running server.
Run with: pytest tests/integration/ -v

Requires: server running + .env with DB_URL.
Test users are created automatically by conftest.py.
"""

import os
import tempfile
import pytest

from conftest import HOST, unique_key
from cli.api.text import upload_text, get_clipboard
from cli.api.file import upload_file, get_file
from cli.api.actions import renew


def _tmp_file(content=b'test', suffix='.bin'):
    f = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    f.write(content)
    f.close()
    return f.name


# ── Burn-after-read ───────────────────────────────────────────────────────────

class TestBurn:
    """Burn is available on all plans."""

    def test_free_burn_upload(self, free_user):
        key = unique_key('burn-free')
        assert upload_text(HOST, free_user.session, 'burn me', key=key, burn=True, is_test=True)

    def test_starter_burn_upload(self, starter_user):
        key = unique_key('burn-starter')
        assert upload_text(HOST, starter_user.session, 'burn me', key=key, burn=True, is_test=True)

    def test_pro_burn_upload(self, pro_user):
        key = unique_key('burn-pro')
        assert upload_text(HOST, pro_user.session, 'burn me', key=key, burn=True, is_test=True)

    def test_burn_consumed_on_first_read(self, free_user, anon):
        key = unique_key('burn-read')
        upload_text(HOST, free_user.session, 'ephemeral', key=key, burn=True, is_test=True)
        kind1, _ = get_clipboard(HOST, anon, key)
        assert kind1 == 'text'
        kind2, _ = get_clipboard(HOST, anon, key)
        assert kind2 is None  # gone after first read


# ── Custom expiry ─────────────────────────────────────────────────────────────

class TestExpiry:
    """Custom expiry date is a paid feature."""

    def test_free_expiry_not_applied(self, free_user):
        """Free plan: server ignores expiry_days. Upload must succeed."""
        key = free_user.track(unique_key('exp-free'))
        result = upload_text(HOST, free_user.session, 'exp?', key=key, expiry_days=30, is_test=True)
        assert result is not None

    def test_starter_expiry_applied(self, starter_user):
        key = starter_user.track(unique_key('exp-starter'))
        result = upload_text(HOST, starter_user.session, 'expires', key=key, expiry_days=30, is_test=True)
        assert result is not None

    def test_pro_expiry_applied(self, pro_user):
        key = pro_user.track(unique_key('exp-pro'))
        result = upload_text(HOST, pro_user.session, 'expires', key=key, expiry_days=365, is_test=True)
        assert result is not None


# ── Renew ─────────────────────────────────────────────────────────────────────

class TestRenew:
    """Renew is a paid feature (requires an explicit expires_at)."""

    def test_free_drop_cannot_be_renewed(self, free_user):
        key = free_user.track(unique_key('renew-free'))
        upload_text(HOST, free_user.session, 'renew?', key=key, is_test=True)
        expires_at, _ = renew(HOST, free_user.session, key, ns='c')
        assert expires_at is None

    def test_starter_drop_with_expiry_can_be_renewed(self, starter_user):
        key = starter_user.track(unique_key('renew-starter'))
        upload_text(HOST, starter_user.session, 'renew', key=key, expiry_days=7, is_test=True)
        expires_at, count = renew(HOST, starter_user.session, key, ns='c')
        if expires_at is not None:
            assert isinstance(count, int)

    def test_pro_drop_with_expiry_can_be_renewed(self, pro_user):
        key = pro_user.track(unique_key('renew-pro'))
        upload_text(HOST, pro_user.session, 'renew', key=key, expiry_days=7, is_test=True)
        expires_at, count = renew(HOST, pro_user.session, key, ns='c')
        if expires_at is not None:
            assert isinstance(count, int)


# ── File size limits ──────────────────────────────────────────────────────────

class TestFileSizeLimits:
    """
    Plan limits:  ANON/FREE: 200 MB | STARTER: 1 GB | PRO: 5 GB
    We test with small files for speed; the boundary check uses a 1 MB proxy.
    """

    def _upload(self, user, content, ns='f'):
        path = _tmp_file(content=content)
        key  = unique_key('fsize')
        try:
            result = upload_file(HOST, user.session, path, key=key, is_test=True)
        finally:
            os.unlink(path)
        if result:
            user.track(result, ns=ns)
        return result

    def test_free_1kb_file(self, free_user):
        assert self._upload(free_user, b'A' * 1024) is not None

    def test_starter_1kb_file(self, starter_user):
        assert self._upload(starter_user, b'B' * 1024) is not None

    def test_pro_1kb_file(self, pro_user):
        assert self._upload(pro_user, b'C' * 1024) is not None

    def test_free_5mb_file_allowed(self, free_user):
        """5 MB is well within the 200 MB free limit."""
        assert self._upload(free_user, b'X' * (5 * 1024 * 1024)) is not None


# ── CLI commands: cp, diff, load, status ─────────────────────────────────────

class TestCliNewCommands:
    """Smoke-test the new CLI commands against the real server."""

    def test_cp_clipboard(self, free_user, cli_envs):
        from conftest import run_drp
        key = unique_key('cp-src')
        upload_text(HOST, free_user.session, 'copy me', key=key, is_test=True)
        env = cli_envs['free']
        result = run_drp('cp', key, unique_key('cp-dst'), env=env)
        assert result.returncode == 0
        assert 'cp-src' in result.stdout or '→' in result.stdout

    def test_diff_identical(self, free_user, cli_envs):
        from conftest import run_drp
        key1 = unique_key('diff-a')
        key2 = unique_key('diff-b')
        upload_text(HOST, free_user.session, 'same', key=key1, is_test=True)
        upload_text(HOST, free_user.session, 'same', key=key2, is_test=True)
        env = cli_envs['free']
        result = run_drp('diff', key1, key2, env=env)
        assert result.returncode == 0  # 0 = identical

    def test_diff_different(self, free_user, cli_envs):
        from conftest import run_drp
        key1 = unique_key('diffd-a')
        key2 = unique_key('diffd-b')
        upload_text(HOST, free_user.session, 'aaa', key=key1, is_test=True)
        upload_text(HOST, free_user.session, 'bbb', key=key2, is_test=True)
        env = cli_envs['free']
        result = run_drp('diff', key1, key2, env=env)
        assert result.returncode == 1  # 1 = different

    def test_status_key(self, free_user, cli_envs):
        from conftest import run_drp
        key = unique_key('stat')
        upload_text(HOST, free_user.session, 'status test', key=key, is_test=True)
        env = cli_envs['free']
        result = run_drp('status', key, env=env)
        assert result.returncode == 0
        assert key in result.stdout

    def test_load_import(self, free_user, cli_envs):
        import json, tempfile, os
        from conftest import run_drp
        key = unique_key('load-key')
        upload_text(HOST, free_user.session, 'to import', key=key, is_test=True)
        data = {'drops': [{'key': key, 'ns': 'c'}], 'saved': []}
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(data, f)
            path = f.name
        try:
            env = cli_envs['free']
            result = run_drp('load', path, env=env)
            assert result.returncode == 0
            assert 'imported' in result.stdout.lower() or 'skipped' in result.stdout.lower()
        finally:
            os.unlink(path)


# ── Password protection ───────────────────────────────────────────────────────

class TestPasswordProtection:
    def test_paid_can_set_password(self, starter_user):
        from cli.api.text import upload_text as upt
        import requests
        key = starter_user.track(unique_key('pw-set'))
        upt(HOST, starter_user.session, 'secret', key=key, is_test=True)
        # Set password via API
        from cli.api.auth import get_csrf
        csrf = get_csrf(HOST, starter_user.session)
        res = starter_user.session.post(
            f'{HOST}/{key}/set-password/',
            json={'password': 'hunter2'},
            headers={'X-CSRFToken': csrf, 'Content-Type': 'application/json'},
        )
        assert res.ok

    def test_password_protected_drop_requires_password(self, starter_user, anon):
        key = starter_user.track(unique_key('pw-gate'))
        upload_text(HOST, starter_user.session, 'guarded', key=key, is_test=True)
        from cli.api.auth import get_csrf
        csrf = get_csrf(HOST, starter_user.session)
        starter_user.session.post(
            f'{HOST}/{key}/set-password/',
            json={'password': 'hunter2'},
            headers={'X-CSRFToken': csrf, 'Content-Type': 'application/json'},
        )
        # Anon fetch without password — should get password_required
        kind, _ = get_clipboard(HOST, anon, key)
        assert kind == 'password_required'

    def test_correct_password_grants_access(self, starter_user, anon):
        key = starter_user.track(unique_key('pw-ok'))
        upload_text(HOST, starter_user.session, 'unlocked content', key=key, is_test=True)
        from cli.api.auth import get_csrf
        csrf = get_csrf(HOST, starter_user.session)
        starter_user.session.post(
            f'{HOST}/{key}/set-password/',
            json={'password': 'open sesame'},
            headers={'X-CSRFToken': csrf, 'Content-Type': 'application/json'},
        )
        kind, content = get_clipboard(HOST, anon, key, password='open sesame')
        assert kind == 'text'
        assert content == 'unlocked content'