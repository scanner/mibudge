from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from rest_framework.authtoken.views import obtain_auth_token

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
    path("auth-token/", obtain_auth_token),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

if settings.DEBUG:
    if "debug_toolbar" in settings.INSTALLED_APPS:
        import debug_toolbar

        urlpatterns = [
            path("__debug__/", include(debug_toolbar.urls))
        ] + urlpatterns
