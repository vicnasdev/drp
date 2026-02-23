"""
tests/unit/conftest.py

Force an in-memory SQLite DB for all unit tests, regardless of any DB_URL
environment variable. This ensures unit tests never touch the real database.
"""

import django
from django.conf import settings


def pytest_configure(config):
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