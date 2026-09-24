"""
Reusable DRF serializer fields for the moneypools v1 API.

`OwnedBankAccountField` resolves a bank account UUID only among the
accounts the requesting user owns.  Serializers that accept a
`bank_account` on create use it so a request body cannot name an
account outside the caller's ownership.  The object-level
`IsAccountOwner` permission never runs on create, so this field is
the primary create-path ownership check (see
`moneypools.permissions.IsAccountOwner` for the full layering).
"""

# 3rd party imports
from django.db.models import QuerySet
from rest_framework import serializers

# Project imports
from moneypools.models import BankAccount


########################################################################
########################################################################
#
class OwnedBankAccountField(serializers.SlugRelatedField):
    """Writable bank account reference scoped to the requesting user.

    Looks the UUID up in `BankAccount.objects.filter(owners=user)`,
    where `user` is `request.user` from the serializer context.  This
    holds for every authentication method (JWT session or API key)
    because both resolve `request.user` to the key's or token's owner.
    An account the user does not own fails validation with the same
    "does not exist" error as a nonexistent UUID, so the response does
    not reveal whether the account exists.

    Without a request in the context (e.g. a serializer instantiated
    for output only) the queryset is empty, so the field fails closed.
    """

    ####################################################################
    #
    def __init__(self, **kwargs: object) -> None:
        """Default to UUID lookup with a placeholder queryset.

        DRF requires a `queryset` on writable related fields at
        construction time; `get_queryset` replaces it per request.

        Args:
            **kwargs: Passed through to `SlugRelatedField`.
        """
        kwargs.setdefault("slug_field", "id")
        if not kwargs.get("read_only"):
            kwargs.setdefault("queryset", BankAccount.objects.none())
        super().__init__(**kwargs)

    ####################################################################
    #
    def get_queryset(self) -> QuerySet[BankAccount]:
        """Return the bank accounts the requesting user owns.

        Returns:
            A queryset of `BankAccount` rows whose `owners` include
            `request.user`, or an empty queryset when there is no
            authenticated request in the serializer context.
        """
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return BankAccount.objects.none()
        return BankAccount.objects.filter(owners=user)
