"""
core/middleware.py

API token authentication middleware.
If request has an Authorization: Bearer <token> header, look up the token
and attach the user to request.user (works alongside session auth).
"""

import hashlib

from django.utils import timezone


class APITokenAuthMiddleware:
    """
    Authenticate requests that carry an ``Authorization: Bearer <token>``
    header.  Runs *after* Django's built-in ``AuthenticationMiddleware`` so
    session-based auth already had a chance to set ``request.user``.  If the
    user is already authenticated via session, the header is ignored.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.user.is_authenticated:
            self._try_token_auth(request)
        return self.get_response(request)

    @staticmethod
    def _try_token_auth(request):
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return

        raw_token = auth[7:].strip()
        if not raw_token:
            return

        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

        from core.models import APIToken
        try:
            api_token = APIToken.objects.select_related("user").get(token_hash=token_hash)
        except APIToken.DoesNotExist:
            return

        if api_token.is_expired():
            return

        # Mark last_used (debounce to avoid a write on every request)
        if (
            api_token.last_used is None
            or (timezone.now() - api_token.last_used).total_seconds() > 300
        ):
            APIToken.objects.filter(pk=api_token.pk).update(last_used=timezone.now())

        request.user = api_token.user
        request._api_token = api_token  # noqa: SLF001
