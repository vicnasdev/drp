"""
Drop action API calls: delete, rename, renew, list, key_exists, save_bookmark.

URL convention:  /<key>/<action>/

Return value conventions for callers (manage.py):
  rename() → new_key string   on success
             False             on a known/reported error (404, 409, 403 …)
             None              on an unexpected error (network, bad JSON, etc.)
  delete() → True / False (unchanged)
  renew()  → (expires_at, renewals) / (None, None) (unchanged)
"""

from .auth import get_csrf
from .helpers import err


def _url(host, key, action):
    return f'{host}/{key}/{action}/'


def delete(host, session, key):
    csrf = get_csrf(host, session)
    try:
        res = session.delete(
            _url(host, key, 'delete'),
            headers={'X-CSRFToken': csrf},
            timeout=10,
        )
        if res.ok:
            return True
        if res.status_code == 404:
            err(f'Drop /{key}/ not found.')
            _report_http('rm', 404, 'delete — not found')
            return False
        _handle_error(res, 'Delete failed')
        _report_http('rm', res.status_code, 'delete')
    except Exception as e:
        err(f'Delete error: {e}')
    return False


def rename(host, session, key, new_key):
    """
    Rename a drop key.

    Returns:
      str   — the new key on success
      False — a known error that has already been printed and reported
               (404, 409 key taken, 403 locked, 400 bad input)
      None  — an unexpected error (network failure, unhandled status code)
               caller should file a SilentFailure report
    """
    csrf = get_csrf(host, session)
    try:
        res = session.post(
            _url(host, key, 'rename'),
            data={'new_key': new_key, 'csrfmiddlewaretoken': csrf},
            timeout=10,
        )
        if res.ok:
            return res.json().get('key')

        if res.status_code == 404:
            err(f'Drop /{key}/ not found.')
            _report_http('mv', 404, 'rename — not found')
            return False

        if res.status_code == 409:
            err(f'Key "{new_key}" is already taken.')
            _report_http('mv', 409, 'rename key conflict')
            return False

        if res.status_code == 403:
            try:
                msg = res.json().get('error', 'Permission denied.')
            except Exception:
                msg = 'Permission denied.'
            err(f'Rename blocked: {msg}')
            _report_http('mv', 403, 'rename')
            return False

        if res.status_code == 400:
            _handle_error(res, 'Rename failed')
            _report_http('mv', 400, 'rename')
            return False

        _handle_error(res, 'Rename failed')
        _report_http('mv', res.status_code, 'rename')

    except Exception as e:
        err(f'Rename error: {e}')

    return None


def renew(host, session, key):
    csrf = get_csrf(host, session)
    try:
        res = session.post(
            _url(host, key, 'renew'),
            data={'csrfmiddlewaretoken': csrf},
            timeout=10,
        )
        if res.ok:
            data = res.json()
            return data.get('expires_at'), data.get('renewals')
        _handle_error(res, 'Renew failed')
        _report_http('renew', res.status_code, 'renew')
    except Exception as e:
        err(f'Renew error: {e}')
    return None, None


def copy_drop(host, session, key, new_key=None):
    """
    Server-side copy of a drop.
    Returns the new key string on success, False on known error, None on unexpected error.
    """
    csrf = get_csrf(host, session)
    payload = {'csrfmiddlewaretoken': csrf}
    if new_key:
        payload['new_key'] = new_key
    try:
        res = session.post(
            _url(host, key, 'copy'),
            data=payload,
            timeout=10,
        )
        if res.ok:
            return res.json().get('key', new_key)
        if res.status_code == 404:
            err(f'Drop /{key}/ not found.')
            _report_http('cp', 404, 'copy — not found')
            return False
        if res.status_code == 409:
            err(f'Key "{new_key}" is already taken.')
            _report_http('cp', 409, 'copy key conflict')
            return False
        if res.status_code == 403:
            try:
                msg = res.json().get('error', 'Permission denied.')
            except Exception:
                msg = 'Permission denied.'
            err(f'Copy blocked: {msg}')
            _report_http('cp', 403, 'copy')
            return False
        _handle_error(res, 'Copy failed')
        _report_http('cp', res.status_code, 'copy')
    except Exception as e:
        err(f'Copy error: {e}')
    return None


def lock_drop(host, session, key, password=None, remove=False):
    """
    Set or remove password on a drop.
    Returns True on success, False on failure.
    """
    csrf = get_csrf(host, session)
    payload = {'csrfmiddlewaretoken': csrf}
    if remove:
        payload['action'] = 'remove'
    elif password:
        payload['password'] = password
    try:
        res = session.post(
            _url(host, key, 'set-password'),
            data=payload,
            timeout=10,
        )
        if res.ok:
            return True
        if res.status_code == 404:
            err(f'Drop /{key}/ not found.')
            return False
        if res.status_code == 403:
            err('Password protection requires a paid plan.')
            return False
        _handle_error(res, 'Lock failed')
        _report_http('lock', res.status_code, 'lock')
    except Exception as e:
        err(f'Lock error: {e}')
    return False


def create_folder(host, session, name, parent_id=None):
    """
    Create a folder. Returns the folder dict on success, None on failure.
    """
    csrf = get_csrf(host, session)
    import json
    payload = {'name': name}
    if parent_id:
        payload['parent_id'] = parent_id
    try:
        res = session.post(
            f'{host}/folders/create/',
            data=json.dumps(payload),
            headers={'X-CSRFToken': csrf, 'Content-Type': 'application/json'},
            timeout=10,
        )
        if res.status_code == 201 or res.ok:
            return res.json()
        if res.status_code == 409:
            err(f'Folder "{name}" already exists.')
            return None
        _handle_error(res, 'Create folder failed')
        _report_http('mkdir', res.status_code, 'create_folder')
    except Exception as e:
        err(f'Create folder error: {e}')
    return None


def save_bookmark(host, session, key):
    """
    Bookmark a drop. Returns True if saved, False on failure.
    Requires login — server returns 403 if not authenticated.
    """
    csrf = get_csrf(host, session)
    try:
        res = session.post(
            _url(host, key, 'save'),
            data={'csrfmiddlewaretoken': csrf},
            timeout=10,
            allow_redirects=False,
        )
        if res.status_code in (301, 302, 303):
            err('drp save requires a logged-in account. Run: drp login')
            return False
        if res.ok:
            return True
        if res.status_code == 403:
            err('drp save requires a logged-in account. Run: drp login')
            return False
        if res.status_code == 404:
            err(f'Drop /{key}/ not found.')
            return False
        _handle_error(res, 'Save failed')
        _report_http('save', res.status_code, 'save_bookmark')
    except Exception as e:
        err(f'Save error: {e}')
    return False


def list_drops(host, session):
    try:
        res = session.get(
            f'{host}/auth/account/',
            headers={'Accept': 'application/json'},
            timeout=15,
        )
        if res.ok:
            return res.json().get('drops', [])
        if res.status_code in (302, 403):
            return None
        err(f'Server returned {res.status_code}.')
        _report_http('ls', res.status_code, 'list_drops')
    except Exception as e:
        err(f'List error: {e}')
    return None


def key_exists(host, session, key):
    try:
        res = session.get(
            f'{host}/check-key/',
            params={'key': key},
            timeout=10,
        )
        if res.ok:
            return not res.json().get('available', True)
    except Exception:
        pass
    return False


def _handle_error(res, prefix):
    try:
        msg = res.json().get('error', res.text[:200])
    except Exception:
        msg = res.text[:200]
    err(f'{prefix}: {msg}')


def _report_http(command: str, status_code: int, context: str) -> None:
    """Fire-and-forget — never raises."""
    try:
        from cli.crash_reporter import report_http_error
        report_http_error(command, status_code, context)
    except Exception:
        pass