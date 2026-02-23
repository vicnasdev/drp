import logging
import os
import sys
import threading
import time

from django.apps import AppConfig

logger = logging.getLogger(__name__)

_scheduler_started = False


def _is_server():
    """True when running under gunicorn or manage.py runserver."""
    if "gunicorn" in sys.modules:
        return True
    return len(sys.argv) > 1 and sys.argv[1] == "runserver"


def _run_scheduler():
    """Background loop that runs cleanup + expiry notifications + weekly feature promotion."""
    from django.core.management import call_command

    interval = int(os.environ.get("CLEANUP_INTERVAL_SECS", 3600))
    promote_every = int(os.environ.get("PROMOTE_INTERVAL_HOURS", 168))  # 168h = 1 week
    hours_since_promote = 0
    time.sleep(30)  # let the app fully start

    while True:
        for cmd in ("cleanup", "send_expiry_notifications"):
            try:
                call_command(cmd)
            except Exception:
                logger.exception("Scheduled %s failed", cmd)

        # Promote top-voted feature proposal → GitHub issue (weekly)
        hours_since_promote += interval / 3600
        if hours_since_promote >= promote_every:
            hours_since_promote = 0
            try:
                call_command("promote_feature")
            except Exception:
                logger.exception("Scheduled promote_feature failed")

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

        # Background scheduler for cleanup + expiry notifications.
        # Runs automatically when serving (gunicorn / runserver), skipped
        # during management commands, migrations, collectstatic, tests, etc.
        global _scheduler_started
        if _is_server() and not _scheduler_started:
            _scheduler_started = True
            t = threading.Thread(target=_run_scheduler, daemon=True)
            t.start()
            logger.info(
                "Background scheduler started (interval: %ss)",
                os.environ.get("CLEANUP_INTERVAL_SECS", "3600"),
            )