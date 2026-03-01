"""
Root conftest — runs before Django settings are loaded.

Sets environment variables so tests always use SQLite, localhost,
and test-safe defaults regardless of what .env contains.
"""

import os

# Override BEFORE Django reads settings (load_dotenv will not overwrite these).
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "project.settings")
os.environ["DB_URL"] = ""          # force SQLite
os.environ["ENVIRONMENT"] = "test"  # no domain mapping
os.environ["DOMAIN"] = ""          # → ALLOWED_HOSTS = localhost
