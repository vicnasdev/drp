"""
Authentication helpers: CSRF token fetching and login.
"""

from .helpers import err


def get_csrf(host, session):
    """Return csrftoken, fetching from server only if not already in session."""
    token = _first_csrf(session)
    if token:
        return token
    # Fetch the login page — guaranteed to set the csrftoken cookie
    # (home page may not render {% csrf_token %} and won't set the cookie)
    session.get(f'{host}/auth/login/', timeout=10)
    return _first_csrf(session) or ''


def _first_csrf(session):
    """Safely get csrftoken even if duplicate cookies exist."""
    for cookie in session.cookies:
        if cookie.name == 'csrftoken':
            return cookie.value
    return None


def login(host, session, email, password):
    """
    Authenticate with the drp server.
    Returns True on success, False on bad credentials.
    Raises requests.RequestException on network errors.
    """
    csrf = get_csrf(host, session)
    res = session.post(
        f'{host}/auth/login/',
        data={'email': email, 'password': password, 'csrfmiddlewaretoken': csrf},
        timeout=10,
        allow_redirects=False,
    )
    return res.status_code in (301, 302)