"""
Management command: send_expiry_notifications

Finds drops where:
  - notify_before_secs is set
  - expires_at is set
  - expires_at - notify_before_secs <= now < expires_at
  - owner has a verified email
  - notification hasn't been sent yet (tracked via a simple flag)

Run via cron: `python manage.py send_expiry_notifications`
"""

from datetime import timedelta

from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.conf import settings
from django.utils import timezone

from core.models import Drop


class Command(BaseCommand):
    help = "Send email notifications for drops approaching expiry"

    def handle(self, *args, **kwargs):
        now = timezone.now()
        # Find drops with notify_before_secs set and expires_at in the future
        candidates = (
            Drop.objects
            .filter(
                notify_before_secs__isnull=False,
                expires_at__isnull=False,
                expires_at__gt=now,
                notified_at__isnull=True,  # not yet notified
            )
            .select_related("owner", "owner__profile")
        )

        sent = 0
        for drop in candidates:
            notify_at = drop.expires_at - timedelta(seconds=drop.notify_before_secs)
            if now < notify_at:
                continue  # too early

            if not drop.owner or not drop.owner.email:
                continue

            # Check email is verified
            profile = getattr(drop.owner, "profile", None)
            if profile and not profile.email_verified:
                continue

            prefix = "f/" if drop.ns == Drop.NS_FILE else ""
            drop_url = f"{settings.DOMAIN}/{prefix}{drop.key}/"
            expires_str = drop.expires_at.strftime("%b %d, %Y at %H:%M UTC")

            from core.models import EmailTemplate
            tpl = EmailTemplate.get('expiry_notification')
            if tpl:
                ctx = dict(prefix=prefix, key=drop.key, drop_url=drop_url, expires_str=expires_str)
                subject = tpl.render_subject(**ctx)
                message = tpl.render_text(**ctx)
                from_email = tpl.get_from_email()
            else:
                subject = f"drp: your drop /{prefix}{drop.key}/ expires soon"
                message = (
                    f"Your drop is expiring on {expires_str}.\n\n"
                    f"  {drop_url}\n\n"
                    f"You can renew it from the drop page or via:\n"
                    f"  drp renew {drop.key}\n\n"
                    f"— drp"
                )
                from_email = settings.DEFAULT_FROM_EMAIL

            try:
                send_mail(
                    subject=subject,
                    message=message,
                    from_email=from_email,
                    recipient_list=[drop.owner.email],
                    fail_silently=True,
                )
                drop.notified_at = now
                drop.save(update_fields=["notified_at"])
                sent += 1
            except Exception as e:
                self.stderr.write(f"Failed to notify for {drop.key}: {e}")

        self.stdout.write(f"Sent {sent} expiry notification(s).")
