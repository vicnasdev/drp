"""
Integration test for com.resend_email.

Sends a real email via Resend. No error = pass.
Requires RESEND_API_KEY in env.
"""

import pytest
from django.conf import settings

from com.resend_email import send


@pytest.mark.skipif(
    not settings.RESEND_API_KEY or not settings.TEST_RECIPIENT_EMAIL,
    reason="RESEND_API_KEY and TEST_RECIPIENT_EMAIL required",
)
def test_send_email():
    send(
        "noreply",
        [settings.TEST_RECIPIENT_EMAIL, f"test@{settings.DOMAIN}"],
        "drp integration test",
        "test",
        {"name": "Integration Runner"},
    )
