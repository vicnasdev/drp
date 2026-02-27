"""Seed superuser profile and email templates."""

from django.db import migrations


def seed(apps, schema_editor):
    User = apps.get_model("auth", "User")
    UserProfile = apps.get_model("core", "UserProfile")
    EmailTemplate = apps.get_model("core", "EmailTemplate")

    if User.objects.filter(pk=1).exists():
        UserProfile.objects.get_or_create(
            user_id=1,
            defaults={
                "plan": "pro",
                "email_verified": True,
                "storage_used_bytes": 0,
                "notify_bug_fix": True,
                "notify_product_updates": True,
                "notify_billing": True,
            },
        )

    EmailTemplate.objects.get_or_create(
        slug="verify_email",
        defaults={
            "subject": "Verify your drp email address",
            "body_html": (
                '<p>Click the link below to verify your email address:</p>\n'
                '<p><a href="{verify_url}">{verify_url}</a></p>'
            ),
        },
    )
    EmailTemplate.objects.get_or_create(
        slug="bug_fix_notification",
        defaults={
            "subject": "Your bug report has been resolved",
            "body_html": (
                '<p>Good news! The issue you reported has been resolved.</p>\n'
                '<p><a href="{issue_url}">View on GitHub</a></p>'
            ),
        },
    )


class Migration(migrations.Migration):
    dependencies = [("core", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
