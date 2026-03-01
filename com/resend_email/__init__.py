"""
Minimal email sender using Resend.

    from com.email import send
    send("noreply", "user@example.com", "Welcome", "welcome", {"name": "Vic"})

Sends from  head@DOMAIN.  HTML template at  templates/email/{template}.html.
Plain-text version is auto-stripped from the HTML.
Falls back to console output when RESEND_API_KEY is not set.
"""

import re
from html import unescape

import resend
from django.conf import settings
from django.template.loader import render_to_string


def _html_to_text(html: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", html)
    text = re.sub(r"<.*?>", "", text)
    return unescape(text).strip()


def send(head: str, to: str | list[str], subject: str, template: str, context: dict | None = None):
    html = render_to_string(f"email/{template}.html", context or {})
    text = _html_to_text(html)
    sender = f"{head}@{settings.DOMAIN}"

    if not settings.RESEND_API_KEY:
        print(f"[email] {sender} → {to}\n  Subject: {subject}\n  {text[:200]}")
        return

    resend.api_key = settings.RESEND_API_KEY
    resend.Emails.send({
        "from": sender,
        "to": to if isinstance(to, list) else [to],
        "subject": subject,
        "html": html,
        "text": text,
    })
