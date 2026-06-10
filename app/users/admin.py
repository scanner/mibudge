# system imports
from typing import Any

# 3rd party imports
from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.contrib.auth import admin as auth_admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.http import HttpRequest
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

# Project imports
import users.invitation as invitation_svc
from common.invitation import window_count
from users.forms import UserChangeForm, UserCreationForm
from users.models import UserInvitation

User = get_user_model()


@admin.register(User)
class UserAdmin(auth_admin.UserAdmin):
    form = UserChangeForm
    add_form = UserCreationForm
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        (_("Personal info"), {"fields": ("name", "email")}),
        (
            _("Permissions"),
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                ),
            },
        ),
        (_("Important dates"), {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("username", "email", "password1", "password2"),
            },
        ),
    )
    list_display = ["username", "email", "name", "is_superuser"]
    search_fields = ["username", "email", "name"]


########################################################################
########################################################################
#
class UserInvitationAdminForm(forms.ModelForm):
    """Creation form for admin-initiated user invitations.

    Only collects invitee_email; invited_by is taken from request.user in
    save_model. Validates against the three service-layer conditions so
    errors surface inline rather than as a 500.
    """

    class Meta:
        model = UserInvitation
        fields = ()

    invitee_email = forms.EmailField(
        label="Invitee email address",
        help_text="Must not already have an active account.",
    )

    ####################################################################
    #
    def clean_invitee_email(self) -> str:
        email = self.cleaned_data["invitee_email"].strip().lower()
        UserModel = get_user_model()

        if UserModel.objects.filter(email=email, is_active=True).exists():
            raise ValidationError(
                f"{email!r} already has an active mibudge account."
            )

        if UserInvitation.objects.filter(
            invitee_email=email,
            status=UserInvitation.Status.PENDING,
            expires_at__gt=timezone.now(),
        ).exists():
            raise ValidationError(
                f"A pending invitation for {email!r} already exists. "
                "Cancel it before creating a new one."
            )

        count = window_count(UserInvitation, email)
        if count >= settings.INVITATION_MAX_PER_WINDOW:
            raise ValidationError(
                f"Too many invitations to {email!r} in the past "
                f"{settings.INVITATION_WINDOW_DAYS} days "
                f"({count} of {settings.INVITATION_MAX_PER_WINDOW})."
            )

        return email


########################################################################
########################################################################
#
@admin.register(UserInvitation)
class UserInvitationAdmin(admin.ModelAdmin):
    """Admin for staff-initiated user invitations.

    Creation delegates to the service layer. State transitions (resend,
    cancel) are available as bulk actions. The detail view is a
    read-only audit trail.
    """

    list_display = (
        "invitee_email",
        "invited_by",
        "status",
        "expires_at",
        "send_count",
        "created_at",
    )
    list_filter = ("status",)
    search_fields = ("invitee_email",)
    ordering = ("-created_at",)
    actions = ["resend_selected_invitations", "cancel_selected_invitations"]

    ####################################################################
    #
    def get_form(
        self,
        request: HttpRequest,
        obj: Any | None = None,
        change: bool = False,
        **kwargs: Any,
    ) -> type[forms.ModelForm]:
        if obj is None:
            return UserInvitationAdminForm
        kwargs["fields"] = ()
        return super().get_form(request, obj, change=change, **kwargs)

    ####################################################################
    #
    def get_fields(
        self, request: HttpRequest, obj: UserInvitation | None = None
    ) -> tuple[str, ...]:
        if obj is None:
            return ("invitee_email",)
        return (
            "invited_by",
            "invitee_email",
            "invitee_user",
            "status",
            "expires_at",
            "accepted_at",
            "cancelled_at",
            "send_count",
            "last_sent_at",
            "token",
            "created_at",
            "modified_at",
        )

    ####################################################################
    #
    def get_readonly_fields(
        self, request: HttpRequest, obj: UserInvitation | None = None
    ) -> tuple[str, ...]:
        if obj is None:
            return ()
        return (
            "invited_by",
            "invitee_email",
            "invitee_user",
            "status",
            "expires_at",
            "accepted_at",
            "cancelled_at",
            "send_count",
            "last_sent_at",
            "token",
            "created_at",
            "modified_at",
        )

    ####################################################################
    #
    def has_change_permission(
        self, request: HttpRequest, obj: UserInvitation | None = None
    ) -> bool:
        if obj is not None:
            return False
        return super().has_change_permission(request, obj)

    ####################################################################
    #
    def has_delete_permission(
        self, request: HttpRequest, obj: UserInvitation | None = None
    ) -> bool:
        return False

    ####################################################################
    #
    def save_model(
        self,
        request: HttpRequest,
        obj: UserInvitation,
        form: UserInvitationAdminForm,
        change: bool,
    ) -> None:
        """Delegate creation to the service layer."""
        if not change:
            invitation = invitation_svc.create_user_invitation(
                inviter=request.user,  # type: ignore[arg-type]
                invitee_email=form.cleaned_data["invitee_email"],
            )
            form.instance = invitation
            return
        super().save_model(request, obj, form, change)

    ####################################################################
    #
    @admin.action(description="Resend invitation email")
    def resend_selected_invitations(
        self,
        request: HttpRequest,
        queryset: Any,
    ) -> None:
        """Resend the invitation email for selected pending invitations."""
        resent = 0
        for inv in queryset.filter(status=UserInvitation.Status.PENDING):
            try:
                invitation_svc.resend_user_invitation(inv)
                resent += 1
            except invitation_svc.InvitationError as exc:
                self.message_user(
                    request,
                    f"Could not resend to {inv.invitee_email}: {exc}",
                    messages.WARNING,
                )
        if resent:
            self.message_user(
                request,
                f"Resent {resent} invitation(s).",
                messages.SUCCESS,
            )

    ####################################################################
    #
    @admin.action(description="Cancel selected invitations")
    def cancel_selected_invitations(
        self,
        request: HttpRequest,
        queryset: Any,
    ) -> None:
        """Cancel all selected pending invitations."""
        cancelled = 0
        for inv in queryset.filter(status=UserInvitation.Status.PENDING):
            try:
                invitation_svc.cancel_user_invitation(inv)
                cancelled += 1
            except invitation_svc.InvitationError:
                pass
        self.message_user(
            request,
            f"Cancelled {cancelled} invitation(s).",
            messages.SUCCESS,
        )
