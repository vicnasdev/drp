from django.conf import settings
from django.contrib.auth.models import AnonymousUser

from core.models import UserProfile


class APITokenAuthMiddleware:
    """
    Resolve ``Authorization: Bearer <token>`` to a user.
    Tokens are looked up by SHA-256 hash in the database.
    Skipped when the table doesn't exist yet (first migrate).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
            user = self._resolve_token(token)
            if user:
                request.user = user
        return self.get_response(request)

    @staticmethod
    def _resolve_token(token):
        import hashlib
        from django.contrib.auth.models import User

        token_hash = hashlib.sha256(token.encode()).hexdigest()
        try:
            from api.models import APIToken
            tok = APIToken.objects.select_related("user").filter(token_hash=token_hash).first()
            return tok.user if tok else None
        except Exception:
            return None
