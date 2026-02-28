"""
core/email_backend.py  —  Resend transactional email backend.

Drop-in Django email backend. Uses urllib (no extra deps).
"""

import json
import urllib.request
import urllib.error
import logging

from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

logger = logging.getLogger(__name__)

RESEND_API = "https://api.resend.com/emails"


class ResendEmailBackend(BaseEmailBackend):
    def send_messages(self, email_messages):
        sent = 0
        api_key = getattr(settings, "RESEND_API_KEY", "")
        if not api_key:
            logger.error("ResendEmailBackend: RESEND_API_KEY not configured")
            return 0

        for msg in email_messages:
            try:
                payload = {
                    "from":    msg.from_email,
                    "to":      msg.to,
                    "subject": msg.subject,
                    "text":    msg.body,
                }
                # attach HTML alternative if present
                for content, mimetype in getattr(msg, "alternatives", []):
                    if mimetype == "text/html":
                        payload["html"] = content
                        break

                req = urllib.request.Request(
                    RESEND_API,
                    data=json.dumps(payload).encode(),
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type":  "application/json",
                    },
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=10):
                    sent += 1
            except urllib.error.HTTPError as e:
                body = e.read().decode(errors="replace")
                logger.error("Resend HTTP error %s: %s", e.code, body)
                if not self.fail_silently:
                    raise
            except Exception as e:
                logger.error("Resend send error: %s", e)
                if not self.fail_silently:
                    raise
        return sent
