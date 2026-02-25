"""
tests/unit/conftest.py

Force an in-memory SQLite DB for all unit tests, regardless of any DB_URL
environment variable. This ensures unit tests never touch the real database.

Mechanism:
  1. pytest_configure sets TESTING=1 *before* Django imports settings.py.
  2. settings.py skips the DB_URL→PostgreSQL override when TESTING=1.
  3. As a safety net, we also override settings.DATABASES here.

No `DB_URL=''` workaround required when running tests.
"""

import os
import django
from django.conf import settings


def pytest_configure(config):
    # Signal to settings.py: do NOT connect to the production database.
    # This must be set before Django imports settings.py.
    # Note: os.environ.pop("DB_URL") does NOT work because load_dotenv()
    # in settings.py re-loads it from .env. The TESTING guard is the fix.
    os.environ["TESTING"] = "1"

    settings.DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": ":memory:",
        }
    }
    settings.DATA_UPLOAD_MAX_MEMORY_SIZE = 50 * 1024 * 1024
    settings.CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.dummy.DummyCache",
        }
    }
    settings.STORAGES = {
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        }
    }


import pytest

@pytest.fixture(autouse=True)
def _invalidate_plan_cache():
    """Reset the PlanLimit in-process cache between tests."""
    from core.models import PlanLimit
    PlanLimit.invalidate_cache()
    yield
    PlanLimit.invalidate_cache()