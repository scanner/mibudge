from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)

from config.views import spa_shell_view
from users.views import (
    cookie_token_obtain_pair_view,
    cookie_token_refresh_view,
)

urlpatterns = [
    # Django Admin
    path(settings.ADMIN_URL, admin.site.urls),
    # User management
    path("users/", include("users.urls", namespace="users")),
    path("accounts/", include("allauth.urls")),
    # Moneypools
    path("mp/", include("moneypools.urls")),
    # REST API -- versioned. All resource endpoints live under /api/v1/
    # so a future v2 can be added without breaking existing clients.
    path("api/v1/", include("config.api_router")),
    # JWT token endpoints are intentionally *outside* the versioned
    # prefix -- auth is cross-version and changing URL on every API
    # bump would churn every client for no reason.
    # /api/token/         -- POST username+password. Sets the refresh token
    #                        as an httpOnly cookie and returns the access
    #                        token in the JSON body. Browser SPA flow.
    # /api/token/refresh/ -- reads refresh token from httpOnly cookie, returns
    #                        new access token (browser SPA flow).
    path("api/token/", cookie_token_obtain_pair_view, name="token-obtain"),
    path("api/token/refresh/", cookie_token_refresh_view, name="token-refresh"),
    # OpenAPI schema + interactive docs for v1. The schema necessarily
    # describes one API version, so it lives under that version's prefix.
    path("api/v1/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/v1/schema/swagger-ui/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
    path(
        "api/v1/schema/redoc/",
        SpectacularRedocView.as_view(url_name="schema"),
        name="redoc",
    ),
    # SPA shell -- serves index.html for /app/ and all sub-paths.
    # Vue Router handles all client-side navigation from here.
    path("app/", spa_shell_view, name="spa-shell"),
    path("app/<path:subpath>", spa_shell_view, name="spa-shell-subpath"),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

if settings.DEBUG:
    if "debug_toolbar" in settings.INSTALLED_APPS:
        import debug_toolbar

        urlpatterns = [
            path("__debug__/", include(debug_toolbar.urls))
        ] + urlpatterns
