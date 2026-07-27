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
    CSRF_TRUSTED_ORIGINS=(list, []),
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
    EMAIL_HOST=(str, ""),
    EMAIL_PORT=(int, 587),
    EMAIL_HOST_USER=(str, ""),
    EMAIL_HOST_PASSWORD=(str, ""),
    EMAIL_USE_TLS=(bool, True),
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
CSRF_TRUSTED_ORIGINS = env("CSRF_TRUSTED_ORIGINS")
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
    "ordered_model",
    "oauth2_provider",
]
LOCAL_APPS = [
    "users.apps.UsersConfig",
    "credentials.apps.CredentialsConfig",
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
LOGIN_URL = "/app/login/"

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
ACCOUNT_EMAIL_VERIFICATION = "mandatory"
ACCOUNT_ADAPTER = "users.adapters.AccountAdapter"
SOCIALACCOUNT_ADAPTER = "users.adapters.SocialAccountAdapter"

# django-rest-framework
# ------------------------------------------------------------------------------
REST_FRAMEWORK = {
    # IMPORTANT: OAuth2 MUST precede JWT.  Both schemes read
    # 'Authorization: Bearer <token>', and simplejwt does not fall
    # through on a token it cannot parse -- it raises InvalidToken (401),
    # so an OAuth2 access token would never reach DOT if JWT ran first.
    # DOT's OAuth2Authentication, by contrast, returns None when the
    # bearer token is not one of its own, so JWT still sees every JWT.
    # The cost is one indexed AccessToken lookup per JWT request; if that
    # ever matters, discriminate on token shape (a JWS has two dots)
    # rather than reordering.
    "DEFAULT_AUTHENTICATION_CLASSES": (
        # OAuth2 access tokens from registered 3rd-party apps
        # ('Authorization: Bearer <token>').  Machine credentials: denied
        # on user/security endpoints via RequiresInteractiveAuth.
        "credentials.authentication.OAuth2Authentication",
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        # Machine credentials ('Authorization: Api-Key <key>').  Denied
        # on user/security endpoints via RequiresInteractiveAuth.
        "credentials.authentication.ApiKeyAuthentication",
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

# API keys
# ------------------------------------------------------------------------------
# APIKey.last_used_at is updated at most once per this interval so bulk
# imports (thousands of requests in minutes) do not write on every request.
API_KEY_LAST_USED_THROTTLE = timedelta(minutes=5)

# Owners of an expiring API key are notified once the expiry is within
# this many days, giving them time to mint a replacement key.
API_KEY_EXPIRY_NOTICE_DAYS = env.int("API_KEY_EXPIRY_NOTICE_DAYS", default=14)

# django-oauth-toolkit (OAuth2 provider)
# ------------------------------------------------------------------------------
# We swap DOT's Application/AccessToken/RefreshToken/Grant/IDToken for
# concrete models in the `credentials` app -- see credentials/models.py
# for why each one must (or should) be owned.  These settings MUST be in
# place before DOT's own migrations run: swapped-out models make DOT's
# CreateModel operations no-ops, and credentials/0003 creates the real
# tables.
#
# DeviceGrant (DOT's sixth swappable model, RFC 8628 device flow) is
# deliberately NOT swapped: it is not part of the Application/token FK
# web (it references the client by a plain client_id string), so owning
# its upgrade migrations would buy nothing today.  Enabling device flow
# later stays additive -- flip on the device-code grant and add the
# verification views; DOT's own DeviceGrant table is used as-is.
OAUTH2_PROVIDER_APPLICATION_MODEL = "credentials.Application"
OAUTH2_PROVIDER_ACCESS_TOKEN_MODEL = "credentials.AccessToken"
OAUTH2_PROVIDER_REFRESH_TOKEN_MODEL = "credentials.RefreshToken"
OAUTH2_PROVIDER_ID_TOKEN_MODEL = "credentials.IDToken"
OAUTH2_PROVIDER_GRANT_MODEL = "credentials.Grant"

OAUTH2_PROVIDER = {
    # PKCE is mandatory for every authorization-code flow (public MCP /
    # desktop / mobile clients).  DOT 3.x already defaults this to True;
    # pinned here so the policy survives a library default change.
    "PKCE_REQUIRED": True,
    # Grant-type policy: authorization-code + PKCE + refresh tokens ONLY.
    # DOT has no single grant-type allowlist; the policy is enforced in
    # three places, and all three must agree:
    #   1. per-app `authorization_grant_type` -- only ever written as
    #      'authorization-code' at registration (checkpoint 4);
    #   2. the COMPLIANT_BCP_RFC9700_* gates below, which reject the
    #      implicit and password grants server-wide;
    #   3. the discovery document (OAUTH2_*_SUPPORTED below), which must
    #      advertise exactly what 1 and 2 accept.
    # Refresh tokens are issued for the auth-code grant automatically and
    # rotate on use (ROTATE_REFRESH_TOKEN, DOT default True).
    #
    # Placeholder scope vocabulary: a single blanket read/write pair
    # until the real taxonomy lands (task-mibudge-auth-scopes).  OAuth2
    # tokens still pass through the RequiresInteractiveAuth gate, so this
    # placeholder does not widen machine-credential access.
    "SCOPES": {
        "read": "Read access to your budgeting data",
        "write": "Read and write access to your budgeting data",
    },
    # Token lifetimes.  The access token mirrors the SPA's JWT access
    # lifetime (60 min) -- short enough that a leaked token is of limited
    # use, long enough that clients are not refreshing constantly.  DOT's
    # own default is 10 hours, which is far too generous for a credential
    # that reaches a user's whole financial history.
    "ACCESS_TOKEN_EXPIRE_SECONDS": 3600,
    # Refresh tokens do NOT expire on a timer: an authorization grant
    # persists until the user revokes it or the app is deregistered
    # (unlike the SPA's 14-day sliding JWT refresh, which is a session).
    # Revocation is therefore the ONLY way a grant ends -- the
    # "Authorized apps" management surface is what makes that usable.
    "REFRESH_TOKEN_EXPIRE_SECONDS": None,
    # Rotate on every use (DOT default; pinned) so a captured refresh
    # token is single-use and reuse is detectable.
    "ROTATE_REFRESH_TOKEN": True,
    # Act on that detection: replaying a rotated-out refresh token
    # revokes the whole token family, so a stolen refresh token buys an
    # attacker one access token before the grant dies and the user is
    # forced back through consent.  DOT defaults this OFF; it is on here
    # because every client is public (PKCE, no client secret) and holds
    # a refresh token that never expires on its own -- precisely the
    # case the protection exists for.
    #
    # NOTE: with reuse protection on, DOT's clear_expired() deliberately
    # RETAINS revoked refresh tokens (they are the detection record) so
    # long as REFRESH_TOKEN_EXPIRE_SECONDS is None.  Those rows
    # therefore accumulate at roughly one per refresh per grant; revisit
    # if the table ever grows enough to matter.
    "REFRESH_TOKEN_REUSE_PROTECTION": True,
    # ...but honor a rotated-out refresh token briefly.  With a 0-second
    # grace period (DOT's default) a client whose refresh response is
    # lost in flight -- a dropped mobile connection, a retried request --
    # retries with a token the server has already consumed and loses the
    # grant outright, forcing the user back through consent.  Two minutes
    # covers a retry without meaningfully widening the replay window.
    "REFRESH_TOKEN_GRACE_PERIOD_SECONDS": 120,
    # Authorization codes are exchanged immediately by a redirected
    # client; 60s (DOT default, pinned) is ample and keeps the window
    # where an intercepted code is useful small.  PKCE already binds the
    # code to the client that requested it.
    "AUTHORIZATION_CODE_EXPIRE_SECONDS": 60,
    # RFC 8414 discovery document (/.well-known/oauth-authorization-server).
    # DOT's defaults advertise implicit, password, client-credentials and
    # device-code -- every one of which this server rejects.  A discovery
    # document that lies sends clients down flows that will fail, so these
    # are narrowed to what is actually accepted.  Endpoint URLs are not
    # listed here: DOT reverse()s them and omits any that are not mounted,
    # which is what keeps the unmounted device-flow endpoints out.
    # Surface `visibility`/`status` in the admin and drop DOT's
    # "View on site" link, which points at an unmounted view.
    "APPLICATION_ADMIN_CLASS": "credentials.admin.ApplicationAdmin",
    "OAUTH2_GRANT_TYPES_SUPPORTED": ["authorization_code", "refresh_token"],
    "OAUTH2_RESPONSE_TYPES_SUPPORTED": ["code"],
    # 'none' is the RFC 8414 value for public clients, which is what MCP /
    # desktop / mobile apps are.  The two client_secret_* methods stay for
    # confidential clients (our own hosted importers, registered as global
    # apps) -- PKCE is required of both.
    "OAUTH2_TOKEN_ENDPOINT_AUTH_METHODS_SUPPORTED": [
        "none",
        "client_secret_post",
        "client_secret_basic",
    ],
    # RFC 9700 (OAuth 2.0 Security BCP) gates.  DOT defaults every one of
    # these to False for backwards compatibility and flips them in 4.0;
    # adopting them now is what enforces this server's grant policy in the
    # library itself rather than only at registration time.
    #
    # Behaviour gates:
    "COMPLIANT_BCP_RFC9700_IMPLICIT_GRANT": True,  # reject implicit
    "COMPLIANT_BCP_RFC9700_PASSWORD_GRANT": True,  # reject password grant
    # Reject the PKCE 'plain' challenge method: it transmits the verifier
    # in the clear and gives no protection against code interception,
    # which is the entire reason PKCE is required here.  S256 only.
    "COMPLIANT_BCP_RFC9700_PKCE_METHOD": True,
    # Reject access tokens passed in the URI query string (they leak into
    # logs, Referer headers, and browser history).  Header only.
    "COMPLIANT_BCP_RFC9700_ACCESS_TOKEN_TRANSPORT": True,
    # RFC 9207: identify this server in the authorization response so a
    # client talking to several providers cannot be tricked into sending
    # our code to another one (mix-up defence).
    "COMPLIANT_BCP_RFC9700_AUTHZ_RESPONSE_ISS": True,
    #
    # Config-validation gates: these change no behaviour, they raise the
    # severity of `manage.py check --deploy` from Warning to Error when
    # the setting they cover is on a non-compliant value.  The covered
    # settings are all compliant above, so turning these on costs nothing
    # today and makes a future regression fail the deploy check.
    "COMPLIANT_BCP_RFC9700_REFRESH_TOKEN": True,
    "COMPLIANT_BCP_RFC9700_REDIRECT_URI_MATCHING": True,
    "COMPLIANT_BCP_RFC9700_PKCE_REQUIRED": True,
    #
    # Two gates are deliberately left OFF:
    #
    # COMPLIANT_BCP_RFC9700_REDIRECT_URI_SCHEME would forbid 'http'
    # redirect URIs, which also forbids the http://127.0.0.1 loopback
    # callback that RFC 8252 native apps -- desktop, mobile, and MCP
    # clients, i.e. most of our intended consumers -- must use.  Keeping
    # 'http' allowed does mean a registered redirect URI could point at a
    # plaintext remote host, so registration validation must restrict
    # http to loopback (checkpoint 4).
    #
    # COMPLIANT_BCP_RFC9700_TOKEN_STORAGE (hash tokens at rest, like
    # APIKey does) is mutually exclusive with
    # REFRESH_TOKEN_GRACE_PERIOD_SECONDS > 0 -- DOT raises E001 -- because
    # honouring a rotated-out refresh token means returning the previously
    # issued token, which a hash cannot reproduce.  The grace period was
    # chosen deliberately; revisit the trade-off if that changes.
}

# The OAuth2 consent flow's own login page (/o/login/) accepts a
# password, so it needs a brute-force limit of its own -- it is a plain
# Django view and none of DRF's throttling applies to it.  Counted per
# submitted email address; see credentials.views.OAuth2LoginView for why
# not per IP.
OAUTH2_LOGIN_MAX_ATTEMPTS = env.int("OAUTH2_LOGIN_MAX_ATTEMPTS", default=10)
OAUTH2_LOGIN_WINDOW_SECONDS = env.int(
    "OAUTH2_LOGIN_WINDOW_SECONDS", default=900
)

# drf-spectacular
# ------------------------------------------------------------------------------
SPECTACULAR_SETTINGS = {
    "TITLE": "mibudge API",
    "DESCRIPTION": (
        "REST API for the mibudge personal budgeting service.\n\n"
        # NOTE: no '## Authentication' section here -- each scheme
        # documents itself in components.securitySchemes (see
        # credentials/authentication.py and users/schema.py), and the
        # generated docs render those under their own Authentication
        # heading.  Describing the schemes here too duplicated the
        # heading and went stale the moment a third method landed.
        "Every endpoint requires authentication. Three credentials are "
        "accepted -- an interactive JWT, a machine API key, or an "
        "OAuth2 access token -- each described under Authentication "
        "below. Machine credentials (API keys and OAuth2 tokens) are "
        "refused on user/security endpoints.\n\n"
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
    # Describe the one OAuth2 flow this server offers, so Swagger UI can
    # drive it.  Only 'authorizationCode' is listed -- the implicit,
    # password and client-credentials flows are rejected (see the RFC
    # 9700 gates in OAUTH2_PROVIDER) and must not be advertised here
    # either.  Scopes are read from OAUTH2_PROVIDER['SCOPES'] by
    # drf-spectacular's DOT extension when OAUTH2_SCOPES is unset.
    "OAUTH2_FLOWS": ["authorizationCode"],
    "OAUTH2_AUTHORIZATION_URL": "/o/authorize/",
    "OAUTH2_TOKEN_URL": "/o/token/",
    # Three models expose a 'status' field with different choice sets;
    # name each component explicitly so spectacular does not fall back
    # to hash-suffixed names like 'Status58bEnum'.  NOTE: no trailing
    # '.choices' -- spectacular's deep_import_string resolves at most
    # MODULE.OBJECT.ATTRIBUTE, and it unwraps Choices classes itself.
    "ENUM_NAME_OVERRIDES": {
        "FundingEventStatusEnum": (
            "moneypools.models.FundingEventOccurrence.Status"
        ),
        "BankAccountInvitationStatusEnum": (
            "moneypools.models.BankAccountInvitation.Status"
        ),
        "UserInvitationStatusEnum": "users.models.UserInvitation.Status",
        "OAuth2ApplicationStatusEnum": "credentials.models.Application.Status",
    },
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
