"""
Moucharaka platform settings.

Every deployment-specific value comes from environment variables (or a .env
file next to manage.py), so the same code runs on a VPS, Docker, cPanel /
Passenger hosting, Render, Railway, Heroku-like PaaS, etc.
"""
import sys
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
    CSRF_TRUSTED_ORIGINS=(list, []),
    SECURE_SSL_REDIRECT=(bool, False),
    USE_X_FORWARDED_PROTO=(bool, False),
)
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY", default="dev-insecure-change-me")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env("CSRF_TRUSTED_ORIGINS")
# Render publishes the service's own hostname (xxx.onrender.com)
RENDER_EXTERNAL_HOSTNAME = env("RENDER_EXTERNAL_HOSTNAME", default="")
if RENDER_EXTERNAL_HOSTNAME:
    ALLOWED_HOSTS = [*ALLOWED_HOSTS, RENDER_EXTERNAL_HOSTNAME]
    CSRF_TRUSTED_ORIGINS = [*CSRF_TRUSTED_ORIGINS, "https://" + RENDER_EXTERNAL_HOSTNAME]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "rest_framework",
    "rest_framework.authtoken",
    "django_filters",
    # Local apps
    "apps.core",
    "apps.sms",
    "apps.accounts",
    "apps.projects",
    "apps.wallet",
    "apps.investments",
    "apps.market",
    "apps.contracts",
    "apps.trust",
    "apps.staff",
    "apps.api",
]

MIDDLEWARE = [
    "apps.core.middleware.HealthCheckMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "django.template.context_processors.i18n",
                "apps.core.context_processors.platform",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# Database: sqlite by default, any DATABASE_URL otherwise
# (postgres://..., mysql://... for shared hosting)
DATABASES = {
    "default": env.db("DATABASE_URL", default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}")
}
DATABASES["default"]["ATOMIC_REQUESTS"] = False
DATABASES["default"]["CONN_MAX_AGE"] = env.int("CONN_MAX_AGE", default=60)

AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = ["apps.accounts.backends.PhoneBackend"]
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "core:dashboard"
LOGOUT_REDIRECT_URL = "core:home"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ---------------------------------------------------------------- i18n
LANGUAGE_CODE = env("LANGUAGE_CODE", default="ar")
FORMAT_MODULE_PATH = ["config.formats"]  # Arabic: "." for decimals (see config/formats/ar)
LANGUAGES = [("ar", "العربية"), ("fr", "Français")]
LOCALE_PATHS = [BASE_DIR / "locale"]
TIME_ZONE = "Africa/Nouakchott"
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------- static / media
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_URL = "/media/"
MEDIA_ROOT = Path(env("MEDIA_ROOT", default=str(BASE_DIR / "media")))
# Identity documents never live under MEDIA_ROOT: they are served only by a
# permission-checking view (apps.accounts.views.private_file).
PRIVATE_MEDIA_ROOT = Path(env("PRIVATE_MEDIA_ROOT", default=str(BASE_DIR / "private_media")))
SERVE_MEDIA = env.bool("SERVE_MEDIA", default=True)

# Hashed, compressed static files once `collectstatic` has been run (production).
# Without it (local run with DEBUG=False, first deploy), fall back to serving
# straight from static/ so the site never crashes on a missing manifest.
STATIC_COLLECTED = (STATIC_ROOT / "staticfiles.json").exists() or "collectstatic" in sys.argv
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
        if (STATIC_COLLECTED and not DEBUG) else "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}
WHITENOISE_USE_FINDERS = not STATIC_COLLECTED
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
MAX_UPLOAD_MB = env.int("MAX_UPLOAD_MB", default=8)

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------- cache (OTP throttling)
CACHES = {"default": env.cache("CACHE_URL", default="locmemcache://")}

# ---------------------------------------------------------------- email (optional)
EMAIL_CONFIG = env.email("EMAIL_URL", default="consolemail://")
vars().update(EMAIL_CONFIG)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="no-reply@moucharaka.mr")

# ---------------------------------------------------------------- security
SESSION_COOKIE_SECURE = not DEBUG and env.bool("COOKIE_SECURE", default=True)
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
SESSION_COOKIE_HTTPONLY = True
SECURE_SSL_REDIRECT = env("SECURE_SSL_REDIRECT")
if env("USE_X_FORWARDED_PROTO"):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=0)
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SESSION_COOKIE_AGE = 60 * 60 * 24 * 14

# ---------------------------------------------------------------- REST API
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.TokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticatedOrReadOnly"],
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {"anon": "60/min", "user": "240/min", "otp": "5/hour"},
}

# ---------------------------------------------------------------- platform
PLATFORM_NAME = env("PLATFORM_NAME", default="Moucharaka")
CURRENCY = "MRU"
OTP_LENGTH = 6
OTP_TTL_SECONDS = env.int("OTP_TTL_SECONDS", default=300)
OTP_MAX_ATTEMPTS = 5
OTP_MAX_PER_HOUR = env.int("OTP_MAX_PER_HOUR", default=5)
# Testing without WhatsApp: show every code on the page (sign-up, login, password reset, withdrawals).
# Anyone can then use a number that is not theirs, so set it back to False before the public launch.
OTP_SHOW_ON_SCREEN = env.bool("OTP_SHOW_ON_SCREEN", default=False)
# Phones: numbers typed without "+" are read as Mauritanian.
PHONE_DEFAULT_REGION = env("PHONE_DEFAULT_REGION", default="MR")
# Countries allowed to register (ISO codes, "*" = the whole world). WhatsApp codes
# are not exposed to SMS premium-rate fraud, so the default is worldwide; restrict
# (e.g. "MR,FR,ES,AE") if you also enable SMS fallback.
PHONE_ALLOWED_COUNTRIES = env.list("PHONE_ALLOWED_COUNTRIES", default=["*"])
# Messaging: WhatsApp first, SMS only if an SMS provider is configured.
OTP_CHANNELS = env.list("OTP_CHANNELS", default=["whatsapp", "sms"])
NOTIFICATION_CHANNELS = env.list("NOTIFICATION_CHANNELS", default=["whatsapp"])
# Used when no provider is configured in the admin (console = print to the log, for development).
MESSAGING_FALLBACK_BACKEND = env("MESSAGING_FALLBACK_BACKEND", default=env("SMS_FALLBACK_BACKEND", default="console"))
SMS_FALLBACK_BACKEND = MESSAGING_FALLBACK_BACKEND
# A newly added payment account must wait this long before receiving a
# withdrawal (unless a deposit from it was already confirmed).
NEW_PAYMENT_ACCOUNT_HOLD_HOURS = env.int("NEW_PAYMENT_ACCOUNT_HOLD_HOURS", default=24)
MAX_PAYMENT_ACCOUNTS = 6
# Shared secret used to verify payment provider webhooks (HMAC-SHA256).
PAYMENT_WEBHOOK_SECRET = env("PAYMENT_WEBHOOK_SECRET", default="")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
}

# Keep test uploads out of real media folders

if len(sys.argv) > 1 and sys.argv[1] == "test":
    MEDIA_ROOT = BASE_DIR / ".test_media" / "public"
    PRIVATE_MEDIA_ROOT = BASE_DIR / ".test_media" / "private"
    PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
    STORAGES["staticfiles"]["BACKEND"] = "django.contrib.staticfiles.storage.StaticFilesStorage"
