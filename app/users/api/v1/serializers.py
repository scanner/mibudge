from django.contrib.auth import get_user_model
from django.contrib.auth.base_user import AbstractBaseUser
from rest_framework import serializers
from zxcvbn import zxcvbn

from moneypools.models import BankAccount

User = get_user_model()


########################################################################
########################################################################
#
class ChangePasswordSerializer(serializers.Serializer):
    """Validate a password-change request.

    Checks that the new password is strong enough (zxcvbn score >= 2)
    and that the two new-password fields match.  Current-password
    verification and the actual password update are handled in the view.
    """

    current_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)
    confirm_password = serializers.CharField(write_only=True)

    ####################################################################
    #
    def validate_new_password(self, value: str) -> str:
        """Reject passwords that score below 2 on the zxcvbn scale.

        Args:
            value: The proposed new password.

        Returns:
            The password string if it is strong enough.

        Raises:
            ValidationError: If zxcvbn rates the password too weak,
                including any warning and suggestions from the library.
        """
        user = self.context.get("user")
        user_inputs: list[str] = []
        if user is not None:
            user_inputs = [
                v
                for v in [user.username, user.email, getattr(user, "name", "")]
                if v
            ]
        result = zxcvbn(value, user_inputs=user_inputs)
        if result["score"] < 2:
            fb = result.get("feedback", {})
            messages: list[str] = []
            if fb.get("warning"):
                messages.append(fb["warning"])
            messages.extend(fb.get("suggestions", []))
            if not messages:
                messages = ["Password is too weak."]
            raise serializers.ValidationError(messages)
        return value

    ####################################################################
    #
    def validate(self, data: dict) -> dict:
        """Validate that new_password and confirm_password match.

        Args:
            data: The incoming field data.

        Returns:
            The validated data dict.

        Raises:
            ValidationError: If the passwords do not match.
        """
        if data["new_password"] != data["confirm_password"]:
            raise serializers.ValidationError(
                {"confirm_password": "Passwords do not match."}
            )
        return data


########################################################################
########################################################################
#
class EmailChangeRequestSerializer(serializers.Serializer):
    """Validate a request to initiate an email-address change."""

    new_email = serializers.EmailField()


class UserSerializer(serializers.ModelSerializer):
    """Serializer for user profiles.

    The ``default_bank_account`` field is writable but constrained:
    the bank account must be owned by the user being updated.  On
    output it returns the UUID string (or null).

    ``has_usable_password`` is read-only and used by the SPA to decide
    whether to enable the change-email and change-password forms.
    """

    default_bank_account = serializers.SlugRelatedField(
        slug_field="id",
        queryset=BankAccount.objects.all(),
        required=False,
        allow_null=True,
    )
    has_usable_password = serializers.SerializerMethodField()

    def get_has_usable_password(self, obj: AbstractBaseUser) -> bool:
        """Return True if the user has a usable (non-unusable) password set."""
        return obj.has_usable_password()

    class Meta:
        model = User
        fields = [
            "username",
            "email",
            "name",
            "url",
            "default_bank_account",
            "timezone",
            "has_usable_password",
        ]

        extra_kwargs = {
            "url": {
                "view_name": "api_v1:user-detail",
                "lookup_field": "username",
            },
            "username": {"read_only": True},
            "email": {"read_only": True},
        }

    ####################################################################
    #
    def validate_default_bank_account(
        self, value: BankAccount | None
    ) -> BankAccount | None:
        """Ensure the bank account is owned by the user being updated.

        Args:
            value: The BankAccount instance, or None.

        Returns:
            The validated BankAccount instance.

        Raises:
            ValidationError: If the account is not owned by this user.
        """
        if value is None or self.instance is None:
            return value
        if not value.owners.filter(id=self.instance.id).exists():
            raise serializers.ValidationError(
                "Bank account is not owned by this user."
            )
        return value
