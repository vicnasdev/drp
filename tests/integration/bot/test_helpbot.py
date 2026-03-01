"""
Integration test for the help bot.

Starts Django server in the background, uses the default Ollama instance,
sends a question through the API, checks the answer, stops the server.

Requires: ollama running locally with LLM_MODEL pulled.
Skipped if ollama is not available.
"""

import os
import shutil
import signal
import subprocess
import time

import pytest
import requests

SERVER_PORT = 18234
OLLAMA_URL = "http://127.0.0.1:11434"


def _wait_for(url, timeout=30):
    for _ in range(timeout * 2):
        try:
            requests.get(url, timeout=1)
            return True
        except Exception:
            time.sleep(0.5)
    return False


@pytest.fixture(scope="module")
def bot_and_server():
    """Ensure Ollama is reachable, start Django runserver, yield, then kill."""
    if not shutil.which("ollama"):
        pytest.skip("ollama not installed")
    if not _wait_for(OLLAMA_URL, timeout=5):
        pytest.skip("ollama not running on default port")

    env = os.environ.copy()
    model = env.get("LLM_MODEL", "qwen2.5:1.5b")

    # ── Create test user in the server's DB before starting ──────
    user_env = {**env, "DJANGO_SETTINGS_MODULE": "project.settings"}
    # Blank these so load_dotenv() in settings.py doesn't restore them.
    user_env["DB_URL"] = ""
    user_env["DOMAIN"] = ""
    user_env["ENVIRONMENT"] = "test"

    subprocess.run(
        ["python", "manage.py", "migrate", "--run-syncdb"],
        env=user_env, capture_output=True, text=True, timeout=30,
    )

    manage = subprocess.run(
        ["python", "manage.py", "shell", "-c",
         "from django.contrib.auth.models import User; "
         "from core.models import UserProfile; "
         "u, c = User.objects.get_or_create(username='bottester', defaults={'email':'bottester@test.local'}); "
         "u.set_password('testpass123'); u.save(); "
         "UserProfile.objects.get_or_create(user=u); "
         "u.is_staff = True; u.save(); "
         "print('user ready')"],
        env=user_env,
        capture_output=True, text=True, timeout=15,
    )
    assert "user ready" in manage.stdout, f"user setup failed: {manage.stderr}"

    # ── Start Django server ───────────────────────────────────────
    server_env = {
        **env,
        "LLM_BASE_URL": f"{OLLAMA_URL}/v1",
        "LLM_MODEL": model,
        "DEBUG": "True",
        "DJANGO_SETTINGS_MODULE": "project.settings",
    }
    server_env["DB_URL"] = ""
    server_env["DOMAIN"] = ""
    server_env["ENVIRONMENT"] = "test"
    server_proc = subprocess.Popen(
        ["python", "manage.py", "runserver", f"127.0.0.1:{SERVER_PORT}", "--noreload"],
        env=server_env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    server_url = f"http://127.0.0.1:{SERVER_PORT}"
    if not _wait_for(f"{server_url}/api/v1/ping/"):
        server_proc.kill()
        pytest.fail("django server failed to start")

    yield server_url

    # ── Cleanup ───────────────────────────────────────────────────
    server_proc.send_signal(signal.SIGTERM)
    server_proc.wait(timeout=5)


@pytest.fixture(scope="module")
def auth_session(bot_and_server):
    """Create a Django session directly and return (server_url, session)."""
    server_url = bot_and_server

    # Build a session inside the server's DB via manage.py shell,
    # bypassing the admin login form (and its CSRF / trusted-origin dance).
    env = os.environ.copy()
    env["DJANGO_SETTINGS_MODULE"] = "project.settings"
    env["DB_URL"] = ""
    env["DOMAIN"] = ""
    env["ENVIRONMENT"] = "test"

    result = subprocess.run(
        ["python", "manage.py", "shell", "-c",
         "from django.contrib.sessions.backends.db import SessionStore; "
         "from django.contrib.auth.models import User; "
         "u = User.objects.get(username='bottester'); "
         "s = SessionStore(); "
         "s['_auth_user_id'] = str(u.pk); "
         "s['_auth_user_backend'] = 'django.contrib.auth.backends.ModelBackend'; "
         "s['_auth_user_hash'] = u.get_session_auth_hash(); "
         "s.create(); "
         "print(s.session_key)"],
        env=env, capture_output=True, text=True, timeout=15,
    )
    session_key = result.stdout.strip()
    assert session_key, f"session creation failed: {result.stderr}"

    session = requests.Session()
    session.cookies.set("sessionid", session_key)

    return server_url, session


def test_helpbot_ask(auth_session):
    server_url, session = auth_session

    resp = session.post(
        f"{server_url}/api/v1/helpbot/",
        json={"question": "What is drp?"},
        timeout=60,
    )

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert "answer" in data
    assert len(data["answer"]) > 0


def test_helpbot_no_auth(bot_and_server):
    server_url = bot_and_server

    # Use GET to avoid CSRF rejection — endpoint only allows POST anyway
    resp = requests.post(
        f"{server_url}/api/v1/helpbot/",
        json={"question": "hello"},
        headers={"Content-Type": "application/json"},
        timeout=10,
    )

    # Either 401 (no auth) or 403 (CSRF) — both mean rejected
    assert resp.status_code in (400, 401, 403)
