"""
Django settings for mibudge.

Single consolidated settings file. All environment-specific configuration
is handled via environment variables with sensible defaults for local
development.
"""

# system imports
import logging
from datetime import timedelta
from pathlib import Path

# 3rd party imports
import environ
from django.utils.crypto import get_random_string

ROOT_DIR = Path(__file__).resolve(strict=True).parent.parent
APPS_DIR = ROOT_DIR
# REPO_DIR is the repository root (one level above the Django project root).
REPO_DIR = ROOT_DIR.parent

# NOTE: We provide our own set of characters because we need to
#       specifically exclude '$' so that environ does not think it is
#       some proxied value.
#
random_chars = "abcdefghijklmnopqrstuvwxyz0123456789!@#%^&*(-_=+)"
env = environ.FileAwareEnv(
    ALLOWED_HOSTS=(list, ["localhost", "0.0.0.0", "127.0.0.1"]),
    CELERY_BROKER_URL=(str, "redis://localhost:6379/1"),
    CELERY_RESULT_BACKEND=(str, "redis://localhost:6379/2"),
    DATABASE_URL=(str, "sqlite:///./db.sqlite3"),
    DEBUG=(bool, False),
    DJANGO_ACCOUNT_ALLOW_REGISTRATION=(bool, False),
    DJANGO_ADMIN_URL=(str, "admin/"),
    DJANGO_DEFAULT_FROM_EMAIL=(
        str,
        "MiBudge <noreply@example.com>",
    ),
    DJANGO_SUPPORT_EMAIL=(str, "support@example.com"),
    DJANGO_EMAIL_BACKEND=(
        str,
        "django.core.mail.backends.smtp.EmailBackend",
    ),
    DJANGO_SECRET_KEY=(str, get_random_string(50, random_chars)),
    REDIS_URL=(str, "redis://localhost:6379/0"),
    SENTRY_DSN=(str, None),
    SENTRY_TRACES_SAMPLE_RATE=(float, 0.0),
)

# Read .env file if it exists (no-op in Docker where env vars are
# injected via docker-compose). Does not override existing env vars.
#
env.read_env(ROOT_DIR.parent / ".env", overwrite=False)

# GENERAL
# ------------------------------------------------------------------------------
DEBUG = env("DEBUG")
SECRET_KEY = env("DJANGO_SECRET_KEY")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")
TIME_ZONE = env("TIME_ZONE", default="America/Los_Angeles")
LANGUAGE_CODE = "en-us"
SITE_ID = 1
REPOSITORY_URL = env(
    "REPOSITORY_URL", default="https://github.com/scanner/mibudge"
)
ADMINISTRATIVE_EMAIL_ADDRESS = env("ADMINISTRATIVE_EMAIL_ADDRESS", default="")
SITE_URL = env("SITE_URL", default="http://localhost:8000")
SITE_NAME = env("SITE_NAME", default="mibudge")
# Human-readable name shown in email subjects, headers, and footers.
# Set per environment so emails clearly identify their source instance:
#   production:        SITE_DISPLAY_NAME=MiBudge
#   integration:       SITE_DISPLAY_NAME=MiBudge [int]
#   dev / local:       SITE_DISPLAY_NAME=MiBudge [dev]
# Users who run their own instance should set this to something distinct
# so their emails cannot be confused with the canonical mibudge.money instance.
SITE_DISPLAY_NAME = env("SITE_DISPLAY_NAME", default="MiBudge [dev]")

# Settings exported to the Django template context via django-settings-export.
# Access in templates as {{ settings.VARIABLE_NAME }}.
#
SETTINGS_EXPORT = [
    "ADMINISTRATIVE_EMAIL_ADDRESS",
    "REPOSITORY_URL",
]
USE_I18N = False
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# DATABASES
# ------------------------------------------------------------------------------
DATABASES = {"default": env.db()}
DATABASES["default"]["ATOMIC_REQUESTS"] = True
if not DEBUG:
    DATABASES["default"]["CONN_MAX_AGE"] = env.int("CONN_MAX_AGE", default=60)

# URLS
# ------------------------------------------------------------------------------
ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

# APPS
# ------------------------------------------------------------------------------
DJANGO_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.sites",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "django.contrib.admin",
]
THIRD_PARTY_APPS = [
    "crispy_forms",
    "crispy_bootstrap5",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "django_celery_beat",
    "django_extensions",
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "drf_spectacular",
    "corsheaders",
    "djmoney",
    "recurrence",
    "django_filters",
    "guardian",
    "django_vite",
]
LOCAL_APPS = [
    "users.apps.UsersConfig",
    "moneypools.apps.MoneyPoolsConfig",
    "notifications.apps.NotificationsConfig",
]
INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

if DEBUG:
    INSTALLED_APPS = ["whitenoise.runserver_nostatic"] + INSTALLED_APPS
    INSTALLED_APPS += ["debug_toolbar"]


# AUTHENTICATION
# ------------------------------------------------------------------------------
AUTHENTICATION_BACKENDS = [
    # Email+password for the SPA/JWT flow -- must come before ModelBackend
    # so authenticate(email=...) is handled here; ModelBackend ignores it.
    #
    "users.backends.EmailBackend",
    # Username+password for Django admin (AdminAuthenticationForm passes
    # username=).
    #
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
    "guardian.backends.ObjectPermissionBackend",
]
AUTH_USER_MODEL = "users.User"
# The SPA owns its own auth flow (silent refresh + /app/login/), so there
# is no allauth-to-SPA handoff URL.  allauth remains mounted for password
# reset flows only.
LOGIN_URL = "account_login"

# PASSWORDS
# ------------------------------------------------------------------------------
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.BCryptSHA256PasswordHasher",
]
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"
    },
]

# MIDDLEWARE
# ------------------------------------------------------------------------------
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

if DEBUG:
    MIDDLEWARE += ["debug_toolbar.middleware.DebugToolbarMiddleware"]

# STATIC
# ------------------------------------------------------------------------------
STATIC_ROOT = str(ROOT_DIR / "staticfiles")
STATIC_URL = "/static/"
STATICFILES_DIRS = [str(APPS_DIR / "static")]
STATICFILES_FINDERS = [
    "django.contrib.staticfiles.finders.FileSystemFinder",
    "django.contrib.staticfiles.finders.AppDirectoriesFinder",
]

# VITE
# ------------------------------------------------------------------------------
# In dev, django-vite proxies asset requests to the Vite dev server.
# In production, it reads the manifest produced by `pnpm run build`.
#
DJANGO_VITE = {
    "default": {
        "dev_mode": env.bool("DJANGO_VITE_DEV_MODE", default=DEBUG),
        "dev_server_protocol": "https",
        "dev_server_port": 5173,
        "manifest_path": REPO_DIR
        / "frontend"
        / "dist"
        / ".vite"
        / "manifest.json",
    }
}

if not env.bool("DJANGO_VITE_DEV_MODE", default=DEBUG):
    # Add the Vite build output to the static files search path so that
    # collectstatic picks up the hashed bundles for production.
    STATICFILES_DIRS += [str(REPO_DIR / "frontend" / "dist")]

# MEDIA
# ------------------------------------------------------------------------------
MEDIA_ROOT = str(APPS_DIR / "media")
MEDIA_URL = "/media/"

# TEMPLATES
# ------------------------------------------------------------------------------
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [str(APPS_DIR / "templates")],
        "OPTIONS": {
            "loaders": [
                "django.template.loaders.filesystem.Loader",
                "django.template.loaders.app_directories.Loader",
            ]
            if DEBUG
            else [
                # django-stubs cannot represent the (loader_class, [loaders]) tuple-in-list
                # format Django uses for the cached template loader -- revisit if stubs improve
                (  # type: ignore[list-item]
                    "django.template.loaders.cached.Loader",
                    [
                        "django.template.loaders.filesystem.Loader",
                        "django.template.loaders.app_directories.Loader",
                    ],
                )
            ],
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.template.context_processors.media",
                "django.template.context_processors.static",
                "django.template.context_processors.tz",
                "django.contrib.messages.context_processors.messages",
                "django_settings_export.settings_export",
            ],
        },
    }
]

# SESSIONS
# ------------------------------------------------------------------------------
SESSION_ENGINE = "django.contrib.sessions.backends.cache"
SESSION_CACHE_ALIAS = "default"

# SECURITY
# ------------------------------------------------------------------------------
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
X_FRAME_OPTIONS = "DENY"

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env.bool("DJANGO_SECURE_SSL_REDIRECT", default=True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = env.int("DJANGO_SECURE_HSTS_SECONDS", default=60)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool(
        "DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", default=True
    )
    SECURE_HSTS_PRELOAD = env.bool("DJANGO_SECURE_HSTS_PRELOAD", default=True)
    SECURE_CONTENT_TYPE_NOSNIFF = env.bool(
        "DJANGO_SECURE_CONTENT_TYPE_NOSNIFF", default=True
    )

# EMAIL
# ------------------------------------------------------------------------------
EMAIL_BACKEND = env("DJANGO_EMAIL_BACKEND")
EMAIL_TIMEOUT = 5
DEFAULT_FROM_EMAIL = env("DJANGO_DEFAULT_FROM_EMAIL")
SERVER_EMAIL = env("DJANGO_SERVER_EMAIL", default=DEFAULT_FROM_EMAIL)
EMAIL_SUBJECT_PREFIX = env("DJANGO_EMAIL_SUBJECT_PREFIX", default="[MiBudge]")
# Support contact address shown in notification emails and error pages.
# Set per deployment -- do not rely on the default in production.
SUPPORT_EMAIL: str = env("DJANGO_SUPPORT_EMAIL")

EMAIL_HOST = env("EMAIL_HOST", default="")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)

# ADMIN
# ------------------------------------------------------------------------------
ADMIN_URL = env("DJANGO_ADMIN_URL")
# Operators who want Django error emails should set this in deployment config.
ADMINS: list[tuple[str, str]] = []
MANAGERS = ADMINS

# LOGGING
# ------------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "%(levelname)s %(asctime)s %(module)s "
            "%(process)d %(thread)d %(message)s"
        }
    },
    "handlers": {
        "console": {
            "level": "DEBUG",
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        }
    },
    "root": {"level": "INFO", "handlers": ["console"]},
}

if not DEBUG:
    LOGGING["disable_existing_loggers"] = True
    LOGGING["loggers"] = {
        "django.db.backends": {
            "level": "ERROR",
            "handlers": ["console"],
            "propagate": False,
        },
        "django.security.DisallowedHost": {
            "level": "ERROR",
            "handlers": ["console"],
            "propagate": False,
        },
    }

# Redis
# ------------------------------------------------------------------------------
REDIS_URL: str = env("REDIS_URL")

# Budget funding
# ------------------------------------------------------------------------------
FUNDING_SYSTEM_USERNAME: str = "funding-system"

# Celery
# ------------------------------------------------------------------------------
CELERY_TIMEZONE = TIME_ZONE
CELERY_BROKER_URL = env("CELERY_BROKER_URL")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND")
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TASK_TIME_LIMIT = 5 * 60
CELERY_TASK_SOFT_TIME_LIMIT = 60
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"

if DEBUG:
    CELERY_TASK_EAGER_PROPAGATES = True

# django-crispy-forms
# ------------------------------------------------------------------------------
CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap5"
CRISPY_TEMPLATE_PACK = "bootstrap5"

# django-allauth
# ------------------------------------------------------------------------------
ACCOUNT_ALLOW_REGISTRATION = env("DJANGO_ACCOUNT_ALLOW_REGISTRATION")
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]
ACCOUNT_USERNAME_REQUIRED = False
ACCOUNT_EMAIL_VERIFICATION = "mandatory"
ACCOUNT_ADAPTER = "users.adapters.AccountAdapter"
SOCIALACCOUNT_ADAPTER = "users.adapters.SocialAccountAdapter"

# django-rest-framework
# ------------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
    "DEFAULT_THROTTLE_CLASSES": (
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ),
    # Rate limits. 'user' is sized to accommodate bulk imports: a year
    # of statements across several accounts can easily exceed several
    # thousand POSTs in a few minutes. The per-minute 'burst' scope
    # (applied selectively on write endpoints via ScopedRateThrottle on
    # specific views if needed) keeps runaway clients bounded without
    # capping normal import workflows. Review these numbers once real
    # usage data is available.
    "DEFAULT_THROTTLE_RATES": {
        "anon": "100/hour",
        "user": "20000/hour",
    },
    "DEFAULT_PAGINATION_CLASS": "config.pagination.FlexiblePageNumberPagination",
    "PAGE_SIZE": 100,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

# drf-spectacular
# ------------------------------------------------------------------------------
SPECTACULAR_SETTINGS = {
    "TITLE": "mibudge API",
    "DESCRIPTION": (
        "REST API for the mibudge personal budgeting service.\n\n"
        "## Authentication\n\n"
        "All endpoints require JWT authentication via "
        "`Authorization: Bearer <token>` header. Obtain tokens "
        "through the login flow; refresh via "
        "`POST /api/token/refresh/` (httpOnly cookie).\n\n"
        "## Permissions\n\n"
        "- **Banks**: read-only, any authenticated user.\n"
        "- **Users**: list/retrieve/update restricted to staff; "
        "`/api/v1/users/me/` available to all authenticated users.\n"
        "- **All other resources** (bank accounts, budgets, transactions, "
        "allocations, internal transactions): scoped to bank account "
        "ownership. Only users in an account's `owners` M2M can "
        "access that account and its related objects. Staff and "
        "superuser status does not bypass ownership checks.\n\n"
        "## Money fields\n\n"
        "Monetary values are represented as a decimal amount paired "
        "with an ISO 4217 currency code (e.g. `amount` + "
        "`amount_currency`). Currency defaults to the account's "
        "currency if not specified."
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "SCHEMA_PATH_PREFIX": "/api/v1/",
}

# djangorestframework-simplejwt
# ------------------------------------------------------------------------------
# Two-token pattern: short-lived access token in JS memory, long-lived
# rotating refresh token in an httpOnly cookie.
#
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=60),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=14),
    # Each refresh call issues a new refresh token and blacklists the old one.
    # This gives a sliding 14-day window: activity resets the clock.
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "ALGORITHM": "HS256",
    "AUTH_HEADER_TYPES": ("Bearer",),
    # Use email as the login field in the SPA/JWT flow (USERNAME_FIELD stays
    # "username" so Django admin is unaffected).
    "TOKEN_OBTAIN_SERIALIZER": "users.serializers.EmailTokenObtainPairSerializer",
}

# django-cors-headers
# ------------------------------------------------------------------------------
CORS_URLS_REGEX = r"^/api/.*$"

# CACHES
# ------------------------------------------------------------------------------
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": env("REDIS_URL"),
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
            "IGNORE_EXCEPTIONS": True,
        },
    }
}

# django-debug-toolbar
# ------------------------------------------------------------------------------
if DEBUG:
    DEBUG_TOOLBAR_CONFIG = {
        "DISABLE_PANELS": ["debug_toolbar.panels.redirects.RedirectsPanel"],
        "SHOW_TEMPLATE_CONTEXT": True,
    }
    INTERNAL_IPS = ["127.0.0.1"]

# Sentry
# ------------------------------------------------------------------------------
SENTRY_DSN = env("SENTRY_DSN")
if SENTRY_DSN is not None:
    import sentry_sdk
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.django import DjangoIntegration
    from sentry_sdk.integrations.logging import LoggingIntegration
    from sentry_sdk.integrations.redis import RedisIntegration

    SENTRY_LOG_LEVEL = env.int("DJANGO_SENTRY_LOG_LEVEL", logging.INFO)
    sentry_logging = LoggingIntegration(
        level=SENTRY_LOG_LEVEL,
        event_level=logging.ERROR,
    )
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[
            sentry_logging,
            DjangoIntegration(),
            CeleryIntegration(),
            RedisIntegration(),
        ],
        environment="devel" if DEBUG else "production",
        traces_sample_rate=env("SENTRY_TRACES_SAMPLE_RATE"),
    )

# Rich tracebacks (development)
# ------------------------------------------------------------------------------
if DEBUG:
    try:
        from rich.traceback import install

        install(show_locals=True)
    except ImportError:
        pass

# Users app
# ------------------------------------------------------------------------------

# How long the new-address verification link is valid.
EMAIL_CHANGE_TOKEN_EXPIRY_HOURS: int = 24

# How long after confirmation the 'this wasn't me' revocation link stays valid.
EMAIL_CHANGE_REVOCATION_DAYS: int = 7

# How long an invitation token is valid.
INVITATION_EXPIRY_DAYS: int = 7

# Per-invitation resend limits: max 3 resends, no more than one per hour.
INVITATION_MAX_RESENDS: int = 3
INVITATION_RESEND_COOLDOWN_HOURS: int = 1

# Per-address abuse prevention: no more than 5 invitations to the same address
# in any 30-day rolling window, regardless of status.
INVITATION_MAX_PER_WINDOW: int = 5
INVITATION_WINDOW_DAYS: int = 30

# Mibudge
# ------------------------------------------------------------------------------
DEFAULT_CURRENCY = "USD"

# Restrict djmoney's currency choices to a curated list of major world
# currencies.  This keeps migration snapshots small and the /api/currencies/
# response focused.  djmoney reads this setting before falling back to the
# full moneyed.CURRENCIES list (300+ entries), so changing this list will
# produce a migration that updates the choices= on all CurrencyField columns
# (a no-op at the database level -- varchar(3) with no DB constraint).
#
CURRENCIES = [
    "USD",  # US Dollar
    "EUR",  # Euro
    "GBP",  # British Pound Sterling
    "CAD",  # Canadian Dollar
    "JPY",  # Japanese Yen
    "AUD",  # Australian Dollar
    "CHF",  # Swiss Franc
    "CNY",  # Chinese Yuan
    "HKD",  # Hong Kong Dollar
    "SGD",  # Singapore Dollar
    "NZD",  # New Zealand Dollar
    "SEK",  # Swedish Krona
    "NOK",  # Norwegian Krone
    "DKK",  # Danish Krone
    "MXN",  # Mexican Peso
    "BRL",  # Brazilian Real
    "INR",  # Indian Rupee
    "KRW",  # South Korean Won
    "ZAR",  # South African Rand
    "TWD",  # New Taiwan Dollar
]

# django-fernet-encrypted-fields
# ------------------------------------------------------------------------------
# NOTE: SALT_KEY is used by django-fernet-encrypted-fields to derive the
# encryption key for sensitive fields stored at rest. The key is derived from
# SECRET_KEY + SALT_KEY using PBKDF2-SHA256.
#
# Key rotation: set SALT_KEY to a comma-separated list of salt strings. The
# first value encrypts all new data; remaining values are tried in order when
# decrypting existing values. To rotate, prepend the new salt:
#
#   .env:         SALT_KEY=new_salt,old_salt
#   settings.py:  SALT_KEY = ["new_salt", "old_salt"]
#
# Once all existing records have been re-saved with the new salt, remove
# the old value from the list.
SALT_KEY = env.list("SALT_KEY")

# Notifications
# ------------------------------------------------------------------------------

# Locale tag used for notification templates when no user-specific locale is
# set, and as the ultimate fallback when a locale-specific template is absent.
# Uses BCP 47 format (matching Django's LANGUAGE_CODE), e.g. 'en-us', 'fr-ca'.
# Template files are named accordingly: email_body.en-us.html, etc.
# Override via env var only when the notification locale should differ from
# the site language.
NOTIFICATIONS_DEFAULT_LOCALE = env(
    "NOTIFICATIONS_DEFAULT_LOCALE", default=LANGUAGE_CODE
)
# Number of days to retain Notification and NotificationLog rows.
# The purge_old_notifications Celery task removes rows older than this.
NOTIFICATIONS_RETENTION_DAYS = env.int(
    "NOTIFICATIONS_RETENTION_DAYS", default=90
)
# Retry config for send_notification_now (immediate CRITICAL dispatch).
# Max retries after the initial attempt; base delay in seconds doubles
# each retry: default schedule is 5m, 10m, 20m, 40m.
NOTIFICATIONS_SEND_MAX_RETRIES = env.int(
    "NOTIFICATIONS_SEND_MAX_RETRIES", default=4
)
NOTIFICATIONS_SEND_RETRY_BASE_DELAY = env.int(
    "NOTIFICATIONS_SEND_RETRY_BASE_DELAY", default=300
)
