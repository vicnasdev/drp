import logging
import os
import threading
import time

from django.apps import AppConfig

logger = logging.getLogger(__name__)

_scheduler_started = False


def _run_scheduler():
    """Background loop that runs cleanup + expiry notifications."""
    from django.core.management import call_command

    interval = int(os.environ.get("CLEANUP_INTERVAL_SECS", 3600))
    time.sleep(30)  # let the app fully start

    while True:
        for cmd in ("cleanup", "send_expiry_notifications"):
            try:
                call_command(cmd)
            except Exception:
                logger.exception("Scheduled %s failed", cmd)
        time.sleep(interval)


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'

    def ready(self):
        # Warm the B2 client once at worker startup so the first request
        # does not pay the boto3 initialization cost (~800ms-1s).
        try:
            from core.views import b2
            b2._b2()
        except Exception:
            pass  # never block startup if B2 credentials are missing

        # NOTE: purge_test_data is intentionally NOT called here.
        # It must be run as a standalone management command before the server
        # starts (e.g. in the deploy entrypoint before gunicorn).
        # Calling it inside ready() triggers a Django RuntimeWarning because
        # ready() is invoked during collectstatic and migrate too, before the
        # app is fully initialised.

        # Start background scheduler for cleanup + notifications.
        # Enable with RUN_SCHEDULER=1 in env (e.g. on Railway).
        global _scheduler_started
        if os.environ.get("RUN_SCHEDULER") == "1" and not _scheduler_started:
            _scheduler_started = True
            t = threading.Thread(target=_run_scheduler, daemon=True)
            t.start()
            logger.info(
                "Background scheduler started (interval: %ss)",
                os.environ.get("CLEANUP_INTERVAL_SECS", "3600"),
            )