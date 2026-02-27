"""
Clipboard (text) drop API calls.
"""

from .auth import get_csrf
from .helpers import err, touch_session, handle_error, handle_http_error, report_http


def upload_text(host, session, text, key=None, timer=None, expiry_days=None,
                burn=False, password=None, is_test=False,
                schedule=None, webhook_url=None, notify=None,
                is_public=False, tags=None, source_url=None):
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
    if schedule:
        data['schedule'] = schedule
    if webhook_url:
        data['webhook_url'] = webhook_url
    if notify:
        data['notify'] = notify
    if is_public:
        data['is_public'] = '1'
    if tags:
        data['tags'] = tags
    if source_url:
        data['source_url'] = source_url
    try:
        res = session.post(f'{host}/save/', data=data, timeout=30)
        if timer:
            timer.checkpoint('upload request')
        if res.ok:
            touch_session()
            return res.json().get('key')
        handle_error(res, 'Upload failed')
        report_http('up', res.status_code, 'upload_text')
    except Exception as e:
        err(f'Upload error: {e}')
    return None


def get_clipboard(host, session, key, timer=None, password=''):
    """
    Fetch a clipboard drop.

    Returns:
      ('text', content_str)        — success
      ('live_error', data_dict)    — live reference fetch failed
      ('binary_ref', data_dict)    — live reference to binary content
      ('password_required', None)  — drop is password-protected, no/wrong password
      (None, None)                 — not found, expired, or other error
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
            touch_session()
            data = res.json()
            if timer:
                timer.checkpoint('parse JSON')
            if data.get('kind') == 'text':
                if data.get('binary'):
                    return 'binary_ref', data
                if data.get('fetch_error'):
                    return 'live_error', data
                return 'text', data.get('content', '')
            return None, None

        handle_http_error(res, key)
        if res.status_code not in (404, 410):
            report_http('get', res.status_code, 'get_clipboard')
    except Exception as e:
        err(f'Get error: {e}')
    return None, None