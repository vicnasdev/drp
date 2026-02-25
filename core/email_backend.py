import resend
from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend


class ResendEmailBackend(BaseEmailBackend):
    def open(self):
        pass

    def close(self):
        pass

    def send_messages(self, email_messages):
        resend.api_key = settings.RESEND_API_KEY
        sent = 0
        for msg in email_messages:
            try:
                # Prefer HTML alternative if present
                body = msg.body
                for content, mimetype in getattr(msg, 'alternatives', []):
                    if mimetype == 'text/html':
                        body = content
                        break
                else:
                    if msg.content_subtype != 'html':
                        body = f'<pre style="font-family:sans-serif;white-space:pre-wrap">{msg.body}</pre>'

                resend.Emails.send({
                    'from': msg.from_email or settings.DEFAULT_FROM_EMAIL,
                    'to': list(msg.to),
                    'subject': msg.subject,
                    'html': body,
                })
                sent += 1
            except Exception as e:
                if not self.fail_silently:
                    raise
                import logging
                logging.getLogger(__name__).error(f"ResendEmailBackend failed to send messages silently: {e}")
        return sent