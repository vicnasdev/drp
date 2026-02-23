"""
management/commands/purge_test_data.py

DEPRECATED: Test drops now use short expires_at (1 hour) and are cleaned
up by the regular ``cleanup`` management command.  This command is kept
only to purge legacy rows that still carry is_test=True.

    python manage.py purge_test_data
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from core.models import Drop, Collection

User = get_user_model()


class Command(BaseCommand):
    help = "Delete legacy data marked is_test=True (deprecated — cleanup handles new test drops)."

    def handle(self, *args, **kwargs):
        # Legacy: delete drops explicitly marked is_test=True.
        drop_count, _ = Drop.objects.filter(is_test=True).delete()

        # Purge collections owned by test users (memberships cascade automatically).
        col_count, _ = Collection.objects.filter(owner__profile__is_test=True).delete()

        test_user_ids = list(
            User.objects.filter(profile__is_test=True).values_list('id', flat=True)
        )
        user_count = len(test_user_ids)
        User.objects.filter(id__in=test_user_ids).delete()

        self.stdout.write(
            f"purge_test_data: removed {user_count} test user(s), "
            f"{drop_count} test drop(s), and {col_count} test collection(s)."
        )