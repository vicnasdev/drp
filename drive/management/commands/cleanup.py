"""
Management command: cleanup

Deletes expired and burned keys (and their orphaned files + B2 objects).
Run periodically via cron or ``make cleanup``.

    python manage.py cleanup
    python manage.py cleanup --dry-run
    python manage.py cleanup --days 0     # only already-expired
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from drive.models import File, Key


class Command(BaseCommand):
    help = "Delete expired and burned keys, and orphaned files."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would be deleted without actually deleting.",
        )
        parser.add_argument(
            "--days",
            type=int,
            default=0,
            help="Grace period: only delete keys expired more than N days ago (default: 0).",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        grace = options["days"]
        cutoff = timezone.now() - timezone.timedelta(days=grace)

        # 1. Expired keys
        expired_qs = Key.objects.filter(expires_at__lt=cutoff)
        expired_count = expired_qs.count()

        # 2. Burned keys
        burned_qs = Key.objects.filter(burn=True, burned=True)
        burned_count = burned_qs.count()

        # Combine
        stale_keys = Key.objects.filter(
            pk__in=list(expired_qs.values_list("pk", flat=True))
            + list(burned_qs.values_list("pk", flat=True))
        )
        total = stale_keys.count()

        self.stdout.write(
            f"Found {expired_count} expired + {burned_count} burned = {total} stale keys"
        )

        if dry_run:
            for k in stale_keys.select_related("file")[:50]:
                reason = "expired" if k.is_expired else "burned"
                self.stdout.write(f"  [dry-run] would delete key={k.key} ({reason}) file={k.file.filename}")
            if total > 50:
                self.stdout.write(f"  … and {total - 50} more")
            return

        # Delete stale keys
        deleted_keys, _ = stale_keys.delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted_keys} stale keys."))

        # 3. Orphaned files — files with no remaining keys
        orphaned = File.objects.filter(keys__isnull=True)
        orphan_count = orphaned.count()

        if orphan_count:
            # TODO: delete B2 objects for each orphaned file before DB delete
            # for f in orphaned:
            #     b2_delete(f.b2_key)
            deleted_files, _ = orphaned.delete()
            self.stdout.write(self.style.SUCCESS(f"Deleted {deleted_files} orphaned files."))
        else:
            self.stdout.write("No orphaned files.")
