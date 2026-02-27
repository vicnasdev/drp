"""Restore superuser profile and email templates after fresh table creation."""

from django.db import migrations


def seed_data(apps, schema_editor):
    User = apps.get_model("auth", "User")
    UserProfile = apps.get_model("core", "UserProfile")
    EmailTemplate = apps.get_model("core", "EmailTemplate")

    # Restore superuser profile (user_id=1) — only if the user exists
    if User.objects.filter(pk=1).exists():
        UserProfile.objects.get_or_create(
            user_id=1,
            defaults={
                "plan": "pro",
                "email_verified": True,
                "storage_used_bytes": 1883026,
                "notify_bug_fix": True,
                "notify_product_updates": True,
                "notify_billing": True,
            },
        )

    # Restore email templates
    EmailTemplate.objects.get_or_create(
        slug="verify_email",
        defaults={
            "subject": "Verify your drp email address",
            "body_html": (
                '<!DOCTYPE html>\n<html lang="en">\n<head>\n'
                '  <meta charset="UTF-8">\n'
                '  <meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
                "</head>\n<body>\n"
                "<p>Click the link below to verify your email address:</p>\n"
                "<p><a href=\"{verify_url}\">{verify_url}</a></p>\n"
                "</body>\n</html>"
            ),
        },
    )
    EmailTemplate.objects.get_or_create(
        slug="bug_fix_notification",
        defaults={
            "subject": "Your bug report has been resolved \U0001f389",
            "body_html": (
                '<!DOCTYPE html>\n<html lang="en">\n<head>\n'
                '  <meta charset="UTF-8">\n'
                '  <meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
                "</head>\n<body>\n"
                "<p>Good news! The issue you reported has been resolved.</p>\n"
                "<p><a href=\"{issue_url}\">View on GitHub</a></p>\n"
                "</body>\n</html>"
            ),
        },
    )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_data, migrations.RunPython.noop),
    ]
