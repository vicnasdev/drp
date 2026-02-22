"""
management/commands/purge_test_data.py

Deletes every User, Drop, and related row that was created by the
integration test suite (is_test=True).

Run in the deploy entrypoint BEFORE gunicorn starts. Safe to run manually:

    python manage.py purge_test_data
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from core.models import Drop

User = get_user_model()


class Command(BaseCommand):
    help = "Delete all data created by the integration test suite (is_test=True)."

    def handle(self, *args, **kwargs):
        # All test drops are explicitly marked is_test=True at creation time
        # (set by the views when the request includes is_test=1/True).
        # Delete them first so SET_NULL on owner FK never produces orphans.
        drop_count, _ = Drop.objects.filter(is_test=True).delete()

        test_user_ids = list(
            User.objects.filter(profile__is_test=True).values_list('id', flat=True)
        )
        user_count = len(test_user_ids)
        User.objects.filter(id__in=test_user_ids).delete()

        self.stdout.write(
            f"purge_test_data: removed {user_count} test user(s) "
            f"and {drop_count} test drop(s)."
        )