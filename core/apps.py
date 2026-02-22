from django.apps import AppConfig


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