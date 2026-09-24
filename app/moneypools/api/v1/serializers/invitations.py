"""
Serializers for bank-account co-ownership invitations in the v1 API.

`BankAccountInvitationSerializer` and `InviteOwnerSerializer` back the
owner-facing invitation actions on `/bank-accounts/`;
`PublicInvitationDetailSerializer` backs the unauthenticated
token-based invitation endpoints.
"""

# 3rd party imports
from rest_framework import serializers

# Project imports
from moneypools.models import BankAccountInvitation


########################################################################
########################################################################
#
class BankAccountInvitationSerializer(serializers.ModelSerializer):
    """Read-only serializer for BankAccountInvitation rows.

    ``token`` is included so the SPA can construct the cancel URL without a
    separate lookup.  It is safe to expose to authenticated account owners
    since they created the invitation and the cancel endpoint enforces that
    only the sender may cancel.

    ``bank_account_id`` and ``bank_account_name`` are included for the
    cross-account listing on the user's settings page (me/invitations/).
    """

    invited_by = serializers.EmailField(
        source="invited_by.email", read_only=True, default=None
    )
    bank_account_id = serializers.UUIDField(
        source="bank_account.id", read_only=True
    )
    bank_account_name = serializers.CharField(
        source="bank_account.name", read_only=True
    )

    class Meta:
        model = BankAccountInvitation
        fields = [
            "id",
            "token",
            "bank_account_id",
            "bank_account_name",
            "invitee_email",
            "invited_by",
            "status",
            "expires_at",
            "accepted_at",
            "declined_at",
            "cancelled_at",
            "created_at",
            "modified_at",
        ]
        read_only_fields = fields


########################################################################
########################################################################
#
class InviteOwnerSerializer(serializers.Serializer):
    """Write-only serializer for the invite-owner action."""

    invitee_email = serializers.EmailField()

    def validate_invitee_email(self, value: str) -> str:
        return value.strip().lower()


########################################################################
########################################################################
#
class PublicInvitationDetailSerializer(serializers.ModelSerializer):
    """Read-only serializer for the public invitation-detail endpoint.

    Returns the minimum information needed to render the acceptance page
    for API clients.  Owner names are intentionally minimal (display name
    or email only) to limit PII exposure behind a bare token.
    """

    bank_account_name = serializers.CharField(
        source="bank_account.name", read_only=True
    )
    bank_name = serializers.CharField(
        source="bank_account.bank.name", read_only=True
    )
    current_owners = serializers.SerializerMethodField()
    is_new_user = serializers.SerializerMethodField()

    class Meta:
        model = BankAccountInvitation
        fields = [
            "id",
            "status",
            "invitee_email",
            "bank_account_name",
            "bank_name",
            "current_owners",
            "is_new_user",
            "expires_at",
        ]
        read_only_fields = fields

    def get_current_owners(self, obj: BankAccountInvitation) -> list[str]:
        return [u.name or u.email for u in obj.bank_account.owners.all()]

    def get_is_new_user(self, obj: BankAccountInvitation) -> bool:
        return (
            obj.invitee_user is not None
            and not obj.invitee_user.has_usable_password()
        )
