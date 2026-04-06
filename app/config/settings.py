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
        "My Budgets <noreply@mibudge.apricot.com>",
    ),
    DJANGO_EMAIL_BACKEND=(
        str,
        "django.core.mail.backends.smtp.EmailBackend",
    ),
    DJANGO_SECRET_KEY=(str, get_random_string(50, random_chars)),
    EMAIL_HOST=(str, "mailpit"),
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
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "django_celery_beat",
    "django_extensions",
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
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
]
INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

if DEBUG:
    INSTALLED_APPS = ["whitenoise.runserver_nostatic"] + INSTALLED_APPS
    INSTALLED_APPS += ["debug_toolbar"]


# AUTHENTICATION
# ------------------------------------------------------------------------------
AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
    "guardian.backends.ObjectPermissionBackend",
]
AUTH_USER_MODEL = "users.User"
LOGIN_REDIRECT_URL = "users:spa-login"
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
            ],
        },
    }
]

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

if DEBUG:
    EMAIL_HOST = env("EMAIL_HOST")
    EMAIL_PORT = 1025
else:
    DEFAULT_FROM_EMAIL = env("DJANGO_DEFAULT_FROM_EMAIL")
    SERVER_EMAIL = env("DJANGO_SERVER_EMAIL", default=DEFAULT_FROM_EMAIL)
    EMAIL_SUBJECT_PREFIX = env(
        "DJANGO_EMAIL_SUBJECT_PREFIX",
        default="[My Budgets]",
    )

# ADMIN
# ------------------------------------------------------------------------------
ADMIN_URL = env("DJANGO_ADMIN_URL")
ADMINS = [("Scanner", "scanner@apricot.com")]
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

# django-allauth
# ------------------------------------------------------------------------------
ACCOUNT_ALLOW_REGISTRATION = env("DJANGO_ACCOUNT_ALLOW_REGISTRATION")
ACCOUNT_LOGIN_METHODS = {"username"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "username*", "password1*", "password2*"]
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
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 40,
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
}

# django-cors-headers
# ------------------------------------------------------------------------------
CORS_URLS_REGEX = r"^/api/.*$"

# CACHES
# ------------------------------------------------------------------------------
if DEBUG:
    CACHES: dict[str, dict[str, object]] = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "",
        }
    }
else:
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

# Mibudge
# ------------------------------------------------------------------------------
DEFAULT_CURRENCY = "USD"
