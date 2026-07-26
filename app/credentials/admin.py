"""Django admin for machine credentials."""

# 3rd party imports
from django.contrib import admin
from django.http import HttpRequest
from oauth2_provider.admin import ApplicationAdmin as DOTApplicationAdmin

# Project imports
from credentials.models import APIKey


########################################################################
########################################################################
#
@admin.register(APIKey)
class APIKeyAdmin(admin.ModelAdmin):
    """Read-only audit view of API keys.

    Keys are created and revoked through the REST API by their owners;
    the admin exists for support and audit.  Key material is never
    visible (only a hash is stored).
    """

    list_display = (
        "name",
        "prefix",
        "user",
        "expires_at",
        "last_used_at",
        "revoked_at",
        "created_at",
    )
    list_filter = ("revoked_at",)
    search_fields = ("name", "prefix", "user__username", "user__email")
    ordering = ("-created_at",)
    readonly_fields = (
        "user",
        "uuid",
        "name",
        "prefix",
        "hashed_key",
        "expires_at",
        "last_used_at",
        "revoked_at",
        "created_at",
        "modified_at",
    )

    ####################################################################
    #
    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    ####################################################################
    #
    def has_change_permission(
        self, request: HttpRequest, obj: APIKey | None = None
    ) -> bool:
        return False

    ####################################################################
    #
    def has_delete_permission(
        self, request: HttpRequest, obj: APIKey | None = None
    ) -> bool:
        return False


########################################################################
########################################################################
#
class ApplicationAdmin(DOTApplicationAdmin):
    """DOT's application admin, with the two mibudge fields surfaced.

    Registered via OAUTH2_PROVIDER['APPLICATION_ADMIN_CLASS'] rather than
    admin.site.register(), which is DOT's supported override hook.

    IMPORTANT: view_on_site is disabled.  DOT's AbstractApplication
    defines get_absolute_url() pointing at its own application-detail
    management view, and that view is deliberately not mounted (see
    credentials/urls.py) -- leaving the link in place makes the admin's
    'View on site' raise NoReverseMatch.
    """

    view_on_site = False

    list_display = (
        "name",
        "user",
        "visibility",
        "status",
        "client_type",
        "authorization_grant_type",
    )
    list_filter = (
        "visibility",
        "status",
        "client_type",
        "authorization_grant_type",
    )
