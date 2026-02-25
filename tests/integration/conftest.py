"""
tests/integration/conftest.py

Zero-setup integration test fixtures. Everything is derived from .env.

Users are created once per session via manage.py shell -c, marked is_test=True,
and left in the DB (purged at next deploy with python manage.py purge_test_data).

Test drops use DRP_TEST_MODE=1 which sets a short expiry (1 hour) so the
regular cleanup cron deletes them automatically.

Plan tiers available as fixtures:
    anon          — unauthenticated requests.Session
    free_user     — test-free@{DOMAIN}    Plan.FREE
    starter_user  — test-starter@{DOMAIN} Plan.STARTER
    pro_user      — test-pro@{DOMAIN}     Plan.PRO

Host resolution:
    DEBUG=True or DOMAIN=localhost  →  http://localhost:8000
    otherwise                       →  https://{DOMAIN}
"""

import json
import os
import secrets
import shutil
import subprocess
from pathlib import Path

import pytest
import requests

# ── Load .env ─────────────────────────────────────────────────────────────────

def _load_dotenv(path):
    p = Path(path)
    if not p.exists():
        return {}
    vals = {}
    for line in p.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, _, v = line.partition('=')
            vals[k.strip()] = v.strip().strip('"').strip("'")
    return vals


_ROOT = Path(__file__).parent.parent.parent
_env  = _load_dotenv(_ROOT / '.env')


def _get(key, default=None):
    return _env.get(key) or os.environ.get(key) or default


# ── Host ──────────────────────────────────────────────────────────────────────

DOMAIN = _get('DOMAIN', 'localhost').rstrip('/')


def _resolve_host():
    debug = _get('DEBUG', 'False').lower() in ('1', 'true', 'yes')
    if debug or DOMAIN == 'localhost':
        return 'http://localhost:8000'
    return f'https://{DOMAIN}'


HOST = _resolve_host()


# ── User management ───────────────────────────────────────────────────────────

def _manage(code):
    # Build env: merge os.environ + .env values, but strip _PYTEST_UNIT
    # so the subprocess uses the real DB_URL (PostgreSQL), not SQLite.
    sub_env = {**os.environ, **_env}
    sub_env.pop('_PYTEST_UNIT', None)
    result = subprocess.run(
        ['python', 'manage.py', 'shell', '-c', code],
        capture_output=True, text=True, cwd=_ROOT,
        env=sub_env,
    )
    if result.returncode != 0:
        raise RuntimeError(f'manage.py shell failed:\n{result.stdout}\n{result.stderr}')
    return result.stdout.strip()


def _create_user(email, password, plan):
    _manage(f"""
from django.contrib.auth import get_user_model
from core.models import UserProfile, Plan
User = get_user_model()
User.objects.filter(email='{email}').delete()
u = User.objects.create_user(username='{email}', email='{email}', password='{password}')
p = UserProfile.objects.get(user=u)
p.plan = Plan.{plan}
p.is_test = True
p.save(update_fields=['plan', 'is_test'])
""")


_TEST_USERS = [
    ('free',    f'test-free@{DOMAIN}',    'FREE'),
    ('starter', f'test-starter@{DOMAIN}', 'STARTER'),
    ('pro',     f'test-pro@{DOMAIN}',     'PRO'),
]


class TestUser:
    """Credentials + authenticated session for one test user."""
    def __init__(self, email, password, plan, session):
        self.email    = email
        self.password = password
        self.plan     = plan
        self.session  = session

    def track(self, key, ns='c'):
        """No-op — test drops auto-expire in 1 hour, cleaned by cron."""
        return key


def _login_session(email, password):
    from cli.api.auth import login as api_login
    s = requests.Session()
    if not api_login(HOST, s, email, password):
        raise RuntimeError(f'Login failed for {email} on {HOST}')
    return s


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope='session')
def users():
    """Create all test users once, yield dict keyed by plan name."""
    password = secrets.token_urlsafe(16)
    created  = {}
    for name, email, plan in _TEST_USERS:
        _create_user(email, password, plan)
        session = _login_session(email, password)
        created[name] = TestUser(email, password, plan, session)
    yield created


@pytest.fixture(scope='session')
def anon():
    return requests.Session()


@pytest.fixture(scope='session')
def free_user(users):    return users['free']


@pytest.fixture(scope='session')
def starter_user(users): return users['starter']


@pytest.fixture(scope='session')
def pro_user(users):     return users['pro']


@pytest.fixture(scope='session')
def host():
    return HOST


# ── CLI env dicts ─────────────────────────────────────────────────────────────

@pytest.fixture(scope='session')
def cli_config_root(tmp_path_factory):
    d = tmp_path_factory.mktemp('drp-integration')
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture(scope='session')
def cli_envs(cli_config_root, users):
    envs = {}
    for name, user in users.items():
        drp_dir = cli_config_root / name / 'drp'
        drp_dir.mkdir(parents=True, exist_ok=True)
        (drp_dir / 'config.json').write_text(json.dumps(
            {'host': HOST, 'email': user.email, 'username': user.email, 'ansi': False}
        ))
        (drp_dir / 'session.json').write_text(json.dumps(dict(user.session.cookies)))
        env = {**os.environ, **_env}
        env['XDG_CONFIG_HOME'] = str(cli_config_root / name)
        env['NO_COLOR'] = '1'
        env['DRP_TEST_MODE'] = '1'
        envs[name] = env
    return envs


@pytest.fixture(scope='session')
def anon_cli_env(cli_config_root):
    drp_dir = cli_config_root / 'anon' / 'drp'
    drp_dir.mkdir(parents=True, exist_ok=True)
    (drp_dir / 'config.json').write_text(json.dumps({'host': HOST, 'ansi': False}))
    env = {**os.environ, **_env}
    env['XDG_CONFIG_HOME'] = str(cli_config_root / 'anon')
    env['NO_COLOR'] = '1'
    env['DRP_TEST_MODE'] = '1'
    return env


@pytest.fixture(scope='session')
def cli_env(anon_cli_env):
    return anon_cli_env


# ── Helpers ───────────────────────────────────────────────────────────────────

PREFIX = 'drptest-'


def unique_key(label=''):
    suffix = secrets.token_urlsafe(6)
    return f'{PREFIX}{label}-{suffix}' if label else f'{PREFIX}{suffix}'


def run_drp(*args, input=None, env=None, check=False):
    result = subprocess.run(
        ['drp', *args], input=input, capture_output=True, text=True, env=env,
    )
    if check and result.returncode != 0:
        raise AssertionError(
            f'drp {" ".join(str(a) for a in args)} exited {result.returncode}\n'
            f'stdout: {result.stdout}\nstderr: {result.stderr}'
        )
    return result

# ── Shared API helpers ────────────────────────────────────────────────────────

import tempfile
import os
from cli.api.auth import get_csrf


def api_post(session, url, data=None, json_body=None):
    """CSRF-aware POST. Sends Referer so proxy + Django CSRF both pass."""
    csrf = get_csrf(HOST, session)
    headers = {
        'X-CSRFToken': csrf,
        'Accept':      'application/json',
        'Referer':     HOST + '/',
    }
    if json_body is not None:
        headers['Content-Type'] = 'application/json'
        return session.post(url, json=json_body, headers=headers)
    return session.post(url, data={**(data or {}), 'csrfmiddlewaretoken': csrf}, headers=headers)


def _tmp_file(content=b'test', suffix='.bin'):
    f = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    f.write(content)
    f.close()
    return f.name


def _fetch_drop_json(session, key, ns='c'):
    """Return the JSON dict for a drop, or None if not found."""
    url = f'{HOST}/f/{key}/' if ns == 'f' else f'{HOST}/{key}/'
    res = session.get(url, headers={'Accept': 'application/json'})
    return res.json() if res.ok else None


def _upload_oversized(session, mb, key=None):
    """Attempt to upload a file of `mb` megabytes. Returns (status_code, result_key)."""
    path = _tmp_file(content=b'X' * (mb * 1024 * 1024), suffix='.bin')
    k    = key or unique_key('oversize')
    try:
        size = os.path.getsize(path)
        csrf = get_csrf(HOST, session)
        res  = session.post(
            f'{HOST}/upload/prepare/',
            json={'filename': 'big.bin', 'size': size,
                  'content_type': 'application/octet-stream', 'ns': 'f', 'key': k},
            headers={'X-CSRFToken': csrf, 'Referer': HOST + '/'},
            timeout=30,
        )
        return res.status_code, None
    finally:
        os.unlink(path)


def _delete_all_collections(session):
    """Delete every collection the session user owns. Safe to call in teardown."""
    for _ in range(3):
        res = session.get(f'{HOST}/auth/account/', headers={'Accept': 'application/json'})
        res.raise_for_status()
        cols = res.json().get('collections', [])
        if not cols:
            return
        for col in cols:
            col_id = col.get('id')
            if col_id:
                r = api_post(session, f'{HOST}/collections/{col_id}/delete/')
                if not r.ok:
                    raise RuntimeError(f'Delete collection {col_id} failed: {r.status_code}')


@pytest.fixture(scope='session')
def plan_limits():
    """
    Fetch live plan limits straight from the DB via Django shell.
    Tests use this instead of hardcoding values so they stay correct
    when limits are changed in the admin.
    Falls back to the hardcoded Plan.LIMITS if no PlanLimit rows exist.
    """
    output = _manage("""
import json
from core.models import PlanLimit, Plan
rows = {row.plan: row.as_dict() for row in PlanLimit.objects.all()}
print(json.dumps(rows if rows else Plan.LIMITS))
""")
    return json.loads(output)