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
    """Return the most authoritative csrftoken.

    Prefer a cookie with a domain attribute (set by the server during a
    response) over a bare cookie (loaded from the JSON session file with no
    domain).  When both exist, they may differ — the domain-matched cookie
    is the one the requests library actually sends in the Cookie header, so
    that is the one Django compares against the X-CSRFToken header.
    """
    domain_token = None
    bare_token = None
    for cookie in session.cookies:
        if cookie.name == 'csrftoken':
            if getattr(cookie, 'domain', ''):
                domain_token = cookie.value
            else:
                bare_token = cookie.value
    return domain_token or bare_token


def login(host, session, identifier, password):
    """
    Authenticate with the drp server using username or email.
    Returns True on success, False on bad credentials.
    Raises requests.RequestException on network errors.
    """
    csrf = get_csrf(host, session)
    res = session.post(
        f'{host}/auth/login/',
        data={'email': identifier, 'password': password, 'csrfmiddlewaretoken': csrf},
        timeout=10,
        allow_redirects=False,
    )
    return res.status_code in (301, 302)