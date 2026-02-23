from pathlib import Path
import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("SECRET_KEY", "django-insecure-changeme")
DEBUG = os.environ.get("DEBUG", "False") == "True"

# Environment: "dev" or "prod" — drives domain, webhooks, and B2 bucket selection.
ENVIRONMENT = os.environ.get("ENVIRONMENT", "dev")

DOMAIN = os.environ.get("DOMAIN")
if not DOMAIN:
    # Sensible defaults per environment
    DOMAIN = {"prod": "drp.fyi", "dev": "drp.vicnas.me"}.get(ENVIRONMENT)
if DOMAIN:
    ALLOWED_HOSTS       = [DOMAIN]
    CSRF_TRUSTED_ORIGINS = [f"https://{DOMAIN}", f"http://{DOMAIN}"]
else:
    ALLOWED_HOSTS        = ["localhost", "127.0.0.1"]
    CSRF_TRUSTED_ORIGINS = ["http://localhost:8000"]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core",
    "billing",
    "help",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "core.middleware.APITokenAuthMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "project.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "project" / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.ads",
                "core.context_processors.domain",
                "core.context_processors.helpbot",
            ],
        },
    },
]

WSGI_APPLICATION = "project.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
        # Prevents "database is locked" OperationalError when multiple Gunicorn
        # workers write concurrently. Workers wait up to 20 s instead of crashing
        # (which propagates as a 500 -> 502 from the upstream proxy).
        "OPTIONS": {
            "timeout": 20,
        },
    }
}

if os.environ.get("DB_URL"):
    import dj_database_url
    DATABASES["default"] = dj_database_url.parse(os.environ.get("DB_URL"))

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE     = "UTC"
USE_I18N      = True
USE_TZ        = True

# Auth
LOGIN_URL            = "/auth/login/"
LOGIN_REDIRECT_URL   = "/"
PASSWORD_RESET_TIMEOUT = 86400  # 24 hours

# Static files
STATIC_URL       = "/static/"
STATICFILES_DIRS = [BASE_DIR / "project" / "static"]
STATIC_ROOT      = BASE_DIR / "project" / "staticfiles"
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

# ── Backblaze B2 ──────────────────────────────────────────────────────────────
B2_KEY_ID       = os.environ.get("B2_KEY_ID", "")
B2_APP_KEY      = os.environ.get("B2_APP_KEY", "")
B2_BUCKET_NAME  = os.environ.get("B2_BUCKET_NAME",
                    "drp-files-test" if ENVIRONMENT == "dev" else "drp-files")
B2_ENDPOINT_URL = os.environ.get("B2_ENDPOINT_URL", "https://s3.us-east-005.backblazeb2.com")

# Admin
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "")

if DOMAIN:
    SITE_URL = f"https://{DOMAIN}"
else:
    SITE_URL = "http://localhost:8000"

# ── Email ─────────────────────────────────────────────────────────────────────
RESEND_API_KEY     = os.environ.get("RESEND_API_KEY", "")
DEFAULT_FROM_EMAIL = os.environ.get(
    "DEFAULT_FROM_EMAIL",
    f"noreply@{DOMAIN}" if DOMAIN else "noreply@localhost",
)

if RESEND_API_KEY:
    EMAIL_BACKEND = os.environ.get("EMAIL_BACKEND", "core.email_backend.ResendEmailBackend")
else:
    EMAIL_BACKEND = os.environ.get(
        "EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend"
    )

# ── Lemon Squeezy ─────────────────────────────────────────────────────────────
LEMONSQUEEZY_API_KEY            = os.environ.get("LEMONSQUEEZY_API_KEY", "")
LEMONSQUEEZY_SIGNING_SECRET     = os.environ.get("LEMONSQUEEZY_SIGNING_SECRET", "")
LEMONSQUEEZY_STORE_ID           = os.environ.get("LEMONSQUEEZY_STORE_ID", "")
LEMONSQUEEZY_STARTER_VARIANT_ID = os.environ.get("LEMONSQUEEZY_STARTER_VARIANT_ID", "")
LEMONSQUEEZY_PRO_VARIANT_ID     = os.environ.get("LEMONSQUEEZY_PRO_VARIANT_ID", "")

ANON_BIN_MAX_SIZE_MB  = 200
CLIPBOARD_MAX_SIZE_KB = 500

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ── Advertising ───────────────────────────────────────────────────────────────
ADSENSE_CLIENT = os.environ.get("ADSENSE_CLIENT", "")
ADSENSE_SLOT   = os.environ.get("ADSENSE_SLOT", "")
# ── Cloudflare Turnstile ──────────────────────────────────────────────────────
# (Turnstile is currently disabled. Keys kept for easy re-enable.)
TURNSTILE_SITE_KEY   = os.environ.get('TURNSTILE_SITE_KEY', '')
TURNSTILE_SECRET_KEY = os.environ.get('TURNSTILE_SECRET_KEY', '')

# ── GitHub webhook ────────────────────────────────────────────────────────────
GITHUB_WEBHOOK_SECRET = os.environ.get('GITHUB_WEBHOOK_SECRET', '')# Hardcoded per environment — no more `make set-domain`
GITHUB_WEBHOOK_URL = f"https://{DOMAIN}/api/github-webhook/" if DOMAIN else ""
# ── Help bot (Gemini) ─────────────────────────────────────────────────────────
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')
GEMINI_MODEL  = os.environ.get('GEMINI_MODEL', 'gemini-2.5-flash-lite')

# ── Bug reports ───────────────────────────────────────────────────────────────
BUG_REPORT_DAILY_LIMIT = 3   # max reports per user per day