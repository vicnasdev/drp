"""
core/middleware.py

APITokenAuthMiddleware: allows CLI / API clients to authenticate via
  Authorization: Bearer <raw_token>
header instead of session cookies.

The raw token is SHA-256 hashed and looked up in APIToken. If found, the
request.user is set to that user for the duration of the request.
"""

import hashlib

from django.contrib.auth import get_user_model
from django.utils import timezone

from .models import APIToken

User = get_user_model()


class APITokenAuthMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.user.is_authenticated:
            auth = request.headers.get("Authorization", "")
            if auth.startswith("Bearer "):
                raw_token = auth[7:].strip()
                token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
                try:
                    token_obj = APIToken.objects.select_related("user").get(token_hash=token_hash)
                    request.user = token_obj.user
                    # update last_used lazily (no signal storm)
                    APIToken.objects.filter(pk=token_obj.pk).update(last_used=timezone.now())
                except APIToken.DoesNotExist:
                    pass

        return self.get_response(request)
