from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from config.views import spa_shell_view
from users.views import cookie_token_refresh_view

urlpatterns = [
    # Django Admin
    path(settings.ADMIN_URL, admin.site.urls),
    # User management
    path("users/", include("users.urls", namespace="users")),
    path("accounts/", include("allauth.urls")),
    # Moneypools
    path("mp/", include("moneypools.urls")),
    # API
    path("api/", include("config.api_router")),
    # JWT refresh -- reads refresh token from httpOnly cookie, returns new access token.
    path("api/token/refresh/", cookie_token_refresh_view, name="token-refresh"),
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
