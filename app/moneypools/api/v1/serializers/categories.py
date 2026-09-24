"""
Serializer for transaction categories in the moneypools v1 API.

`TransactionCategorySerializer` exposes both the global seeded
categories and user-created ones visible to bank-account co-owners.
"""

# 3rd party imports
from django.db.models import Q
from rest_framework import serializers

# Project imports
from moneypools.models import TransactionCategory


########################################################################
########################################################################
#
class TransactionCategorySerializer(serializers.ModelSerializer):
    """Serializer for transaction categories.

    On create the caller supplies group and name; the view forces the
    owner to the requesting user (global rows are managed via the
    django-admin only).  Group and name are whitespace-normalized and
    checked case-insensitively against the global rows and the user's
    own rows for duplicates.  'archived' is toggled via the archive
    action, not writable here.
    """

    owner = serializers.SlugRelatedField(
        slug_field="username",
        read_only=True,
        help_text="Owner username; null for a global category.",
    )
    full_name = serializers.CharField(
        read_only=True,
        help_text="Canonical display form: '{group} : {name}'.",
    )

    class Meta:
        model = TransactionCategory
        fields = [
            "id",
            "group",
            "name",
            "full_name",
            "owner",
            "archived",
            "created_at",
            "modified_at",
        ]
        read_only_fields = [
            "id",
            "full_name",
            "owner",
            "archived",
            "created_at",
            "modified_at",
        ]

    ####################################################################
    #
    def validate_group(self, value: str) -> str:
        """Normalize whitespace and reject colons in the group.

        A colon in the group would break the first-colon split used
        everywhere full names are parsed (export/import, resolver).

        Args:
            value: The proposed group string.

        Returns:
            The whitespace-normalized group.

        Raises:
            ValidationError: If the group is empty or contains a colon.
        """
        value = " ".join(value.split())
        if not value:
            raise serializers.ValidationError("Group must not be empty.")
        if ":" in value:
            raise serializers.ValidationError("Group must not contain a colon.")
        return value

    ####################################################################
    #
    def validate_name(self, value: str) -> str:
        """Normalize whitespace in the name.

        Args:
            value: The proposed name string.

        Returns:
            The whitespace-normalized name.

        Raises:
            ValidationError: If the name is empty.
        """
        value = " ".join(value.split())
        if not value:
            raise serializers.ValidationError("Name must not be empty.")
        return value

    ####################################################################
    #
    def validate(self, attrs: dict) -> dict:
        """Reject case-insensitive duplicates of global or own rows.

        Duplicates of other users' shared categories are allowed --
        those live in the other user's namespace.

        Args:
            attrs: The validated field data.

        Returns:
            The validated attrs dict.

        Raises:
            ValidationError: If an equivalent global or own category
                already exists.
        """
        group = attrs.get(
            "group", self.instance.group if self.instance else None
        )
        name = attrs.get("name", self.instance.name if self.instance else None)
        request = self.context.get("request")
        user = request.user if request is not None else None

        dup_scope = Q(owner__isnull=True)
        if user is not None:
            dup_scope |= Q(owner=user)
        duplicates = TransactionCategory.objects.filter(
            dup_scope, group__iexact=group, name__iexact=name
        )
        if self.instance is not None:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise serializers.ValidationError(
                f"A category '{group} : {name}' already exists."
            )
        return attrs
