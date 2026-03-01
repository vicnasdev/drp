"""
Models for the API app.

CrashReport — deduplicates CLI/web crash reports by fingerprint.
"""

from django.db import models


class CrashReport(models.Model):
    """
    One row per unique crash fingerprint.

    First occurrence files a GitHub issue (if token is configured).
    Subsequent hits just bump ``hit_count`` and ``last_seen``.
    """

    fingerprint = models.CharField(max_length=64, unique=True, db_index=True)
    exc_type = models.CharField(max_length=255)
    exc_message = models.TextField(blank=True, default="")
    traceback = models.TextField(blank=True, default="")
    command = models.CharField(max_length=64, blank=True, default="")
    cli_version = models.CharField(max_length=32, blank=True, default="")
    python_version = models.CharField(max_length=32, blank=True, default="")
    platform = models.CharField(max_length=128, blank=True, default="")

    hit_count = models.PositiveIntegerField(default=1)
    issue_url = models.URLField(blank=True, default="")

    first_seen = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-last_seen"]

    def __str__(self) -> str:
        return f"{self.exc_type} [{self.fingerprint[:8]}] ×{self.hit_count}"
