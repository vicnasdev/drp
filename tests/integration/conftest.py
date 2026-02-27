"""
tests/integration/conftest.py

Fixtures for integration tests that exercise the full upload → store → retrieve
→ download cycle.  B2 is replaced with an in-memory dict so tests stay fast
and never hit a real bucket, while still exercising the Django view layer,
model logic, and storage accounting end-to-end.
"""

import os
import pytest
from unittest.mock import patch

from django.test import override_settings
from django.contrib.auth.models import User

from core.models import Plan, PlanLimit, UserProfile


# ── In-memory B2 storage ─────────────────────────────────────────────────────

class FakeB2:
    """
    Drop-in replacement for the public functions in core.views.b2.

    Objects are stored in ``self.store`` keyed by their B2 object key
    (``drops/f/<key>``).  Presigned URLs are faked as
    ``https://fake-b2/<object_key>``.
    """

    def __init__(self):
        self.store: dict[str, bytes] = {}

    def object_key(self, drop_key: str) -> str:
        return f"drops/f/{drop_key}"

    def upload_fileobj(self, file_obj, drop_key, content_type="application/octet-stream"):
        key = self.object_key(drop_key)
        file_obj.seek(0)
        self.store[key] = file_obj.read()
        return key

    def presigned_put(self, drop_key, content_type="application/octet-stream",
                      size=0, expires_in=3600):
        # In real B2 the client PUTs directly; here we just return a URL.
        # Tests that use the two-step CLI flow will manually call
        # ``fake_b2.store[key] = data`` to simulate the PUT.
        return f"https://fake-b2/{self.object_key(drop_key)}"

    def presigned_get(self, drop_key, filename="", expires_in=3600, b2_key=""):
        obj_key = b2_key if b2_key else self.object_key(drop_key)
        return f"https://fake-b2/{obj_key}"

    def object_head(self, drop_key):
        key = self.object_key(drop_key)
        if key in self.store:
            return {"exists": True, "size": len(self.store[key])}
        return None

    def object_exists(self, drop_key):
        return self.object_key(drop_key) in self.store

    def object_size(self, drop_key):
        key = self.object_key(drop_key)
        return len(self.store[key]) if key in self.store else 0

    def delete_object(self, drop_key, b2_key=""):
        key = b2_key if b2_key else self.object_key(drop_key)
        self.store.pop(key, None)
        return True

    def copy_object(self, src_key, dst_key):
        if src_key in self.store:
            self.store[dst_key] = self.store[src_key]
            return True
        return False


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def fake_b2():
    """
    Patch every public function in ``core.views.b2`` with the in-memory backend.
    Also patches top-level imports in ``core.views.drops`` so functions bound
    at import time (object_head, object_exists, etc.) use the fake too.
    Yields the FakeB2 instance so tests can inspect stored data.
    """
    fb = FakeB2()
    from contextlib import ExitStack
    with ExitStack() as stack:
        # Patch the b2 module itself (covers lazy imports everywhere)
        stack.enter_context(patch("core.views.b2.object_key",       fb.object_key))
        stack.enter_context(patch("core.views.b2.upload_fileobj",   fb.upload_fileobj))
        stack.enter_context(patch("core.views.b2.presigned_put",    fb.presigned_put))
        stack.enter_context(patch("core.views.b2.presigned_get",    fb.presigned_get))
        stack.enter_context(patch("core.views.b2.object_head",      fb.object_head))
        stack.enter_context(patch("core.views.b2.object_exists",    fb.object_exists))
        stack.enter_context(patch("core.views.b2.object_size",      fb.object_size))
        stack.enter_context(patch("core.views.b2.delete_object",    fb.delete_object))
        stack.enter_context(patch("core.views.b2.copy_object",      fb.copy_object))
        # Patch the names that drops.py imported at module level
        stack.enter_context(patch("core.views.drops.object_head",    fb.object_head))
        stack.enter_context(patch("core.views.drops.object_exists",  fb.object_exists))
        stack.enter_context(patch("core.views.drops.object_size",    fb.object_size))
        stack.enter_context(patch("core.views.drops.b2_object_key",  fb.object_key))
        yield fb


_SIMPLE_STATIC = {
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    }
}


@pytest.fixture()
def client(db):
    """Django test client with simple staticfiles backend."""
    from django.test import Client
    with override_settings(STORAGES=_SIMPLE_STATIC):
        yield Client()


@pytest.fixture()
def free_user(db):
    u = User.objects.create_user("free", "free@test.com", "pw12345678")
    # profile auto-created by signal; ensure plan is FREE
    UserProfile.objects.filter(user=u).update(plan=Plan.FREE)
    return u


@pytest.fixture()
def starter_user(db):
    u = User.objects.create_user("starter", "starter@test.com", "pw12345678")
    UserProfile.objects.filter(user=u).update(plan=Plan.STARTER)
    return u


@pytest.fixture()
def pro_user(db):
    u = User.objects.create_user("pro", "pro@test.com", "pw12345678")
    UserProfile.objects.filter(user=u).update(plan=Plan.PRO)
    return u
