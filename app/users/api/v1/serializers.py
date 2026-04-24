from django.contrib.auth import get_user_model
from rest_framework import serializers

from moneypools.models import BankAccount

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    """Serializer for user profiles.

    The ``default_bank_account`` field is writable but constrained:
    the bank account must be owned by the user being updated.  On
    output it returns the UUID string (or null).
    """

    default_bank_account = serializers.SlugRelatedField(
        slug_field="id",
        queryset=BankAccount.objects.all(),
        required=False,
        allow_null=True,
    )

    class Meta:
        model = User
        fields = ["username", "name", "url", "default_bank_account"]

        extra_kwargs = {
            "url": {
                "view_name": "api_v1:user-detail",
                "lookup_field": "username",
            },
            "username": {"read_only": True},
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
