"""
conftest.py — shared fixtures for integration tests.

Every test runs the real `drp` CLI via subprocess against the live server
configured in ~/.config/drp/config.json.  DRP_TEST_MODE=1 is set so
server-created drops auto-expire in 1 hour (cleaned by cron).

Requirements:
  - `drp` installed (pip install -e . from repo root)
  - ~/.config/drp/config.json has host + credentials
  - Server is reachable
"""

import os
import subprocess
import uuid

import pytest


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ENV = {
    **os.environ,
    "DRP_TEST_MODE": "1",
    "NO_COLOR": "1",
    "TERM": "dumb",
}


def _drp(*args, stdin=None, timeout=30):
    cmd = ["python", "-m", "cli.drp"] + list(args)
    proc = subprocess.run(
        cmd, capture_output=True, text=True,
        timeout=timeout, cwd=ROOT, env=ENV,
        input=stdin,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _unique_key(prefix="t"):
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session", autouse=True)
def check_server():
    """Fail fast if the server is unreachable."""
    rc, out, err = _drp("ping")
    if rc != 0:
        pytest.skip(f"Server unreachable — skipping integration tests.\n{out}\n{err}")


@pytest.fixture
def key():
    """Provide a unique key and clean it up after the test."""
    k = _unique_key()
    yield k
    _drp("rm", k)


@pytest.fixture
def text_drop(key):
    """Upload a text drop and return (key, content)."""
    content = f"integration-test-{key}"
    rc, out, _ = _drp("up", content, "-k", key)
    assert rc == 0, f"Failed to create text drop: {out}"
    return key, content


@pytest.fixture
def file_drop(tmp_path):
    """Upload a file drop and return (key, filepath). Cleans up after."""
    k = _unique_key("f")
    p = tmp_path / "test.txt"
    p.write_text("file content for integration test\n")
    rc, out, _ = _drp("up", str(p), "-k", k)
    assert rc == 0, f"Failed to create file drop: {out}"
    yield k, p
    _drp("rm", k)
