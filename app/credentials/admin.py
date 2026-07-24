"""Django admin for machine credentials."""

# 3rd party imports
from django.contrib import admin
from django.http import HttpRequest

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
