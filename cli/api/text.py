"""
Clipboard (text) drop API calls.
"""

from .auth import get_csrf
from .helpers import err


def _touch_session():
    try:
        from cli.session import SESSION_FILE
        SESSION_FILE.touch()
    except Exception:
        pass


def upload_text(host, session, text, key=None, timer=None, expiry_days=None,
                burn=False, password=None, is_test=False):
    """
    Upload text content.
    Returns the key string on success, None on failure.
    """
    csrf = get_csrf(host, session)
    if timer:
        timer.checkpoint('get CSRF token')
    data = {'content': text, 'csrfmiddlewaretoken': csrf}
    if key:
        data['key'] = key
    if expiry_days:
        data['expiry_days'] = expiry_days
    if burn:
        data['burn'] = '1'
    if password:
        data['password'] = password
    if is_test:
        data['is_test'] = '1'
    try:
        res = session.post(f'{host}/save/', data=data, timeout=30)
        if timer:
            timer.checkpoint('upload request')
        if res.ok:
            _touch_session()
            return res.json().get('key')
        _handle_error(res, 'Upload failed')
        _report_http('up', res.status_code, 'upload_text')
    except Exception as e:
        err(f'Upload error: {e}')
    return None


def get_clipboard(host, session, key, timer=None, password=''):
    """
    Fetch a clipboard drop.

    Returns:
      ('text', content_str)       — success
      ('password_required', None) — drop is password-protected, no/wrong password
      (None, None)                — not found, expired, or other error
    """
    headers = {'Accept': 'application/json'}
    if password:
        headers['X-Drop-Password'] = password

    try:
        res = session.get(
            f'{host}/{key}/',
            headers=headers,
            timeout=30,
        )
        if timer:
            timer.checkpoint('HTTP request')

        if res.status_code == 401:
            return 'password_required', None

        if res.ok:
            _touch_session()
            data = res.json()
            if timer:
                timer.checkpoint('parse JSON')
            if data.get('kind') == 'text':
                return 'text', data.get('content', '')
            return None, None

        _handle_http_error(res, key)
        if res.status_code not in (404, 410):
            _report_http('get', res.status_code, 'get_clipboard')
    except Exception as e:
        err(f'Get error: {e}')
    return None, None


def _handle_error(res, prefix):
    try:
        msg = res.json().get('error', res.text[:200])
    except Exception:
        msg = res.text[:200]
    err(f'{prefix}: {msg}')


def _handle_http_error(res, key):
    if res.status_code == 404:
        err(f'Drop /{key}/ not found.')
    elif res.status_code == 410:
        err(f'Drop /{key}/ has expired.')
    else:
        err(f'Server returned {res.status_code}.')


def _report_http(command: str, status_code: int, context: str) -> None:
    try:
        from cli.crash_reporter import report_http_error
        report_http_error(command, status_code, context)
    except Exception:
        pass