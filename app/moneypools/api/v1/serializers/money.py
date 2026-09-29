"""
Money inputs in the moneypools v1 API take their bank account's currency.

A money field (`amount`) arrives with an optional sibling
`<field>_currency`.  `BankAccountCurrencyMixin` resolves each one against
the currency of the bank account the object belongs to: an omitted
currency is the bank account's, and a different one is refused with a 400 on
`<field>_currency`.  djmoney's `MoneyField` fills an omitted currency
with the server default, so the mixin reads what the client actually
sent from `initial_data`, including per item for a list of objects.
"""

# system imports
from typing import Any

# 3rd party imports
from djmoney.contrib.django_rest_framework import MoneyField as DRFMoneyField
from djmoney.money import Money
from rest_framework import serializers


####################################################################
#
def currency_field_name(field_name: str) -> str:
    """The request key carrying a money field's currency."""
    return f"{field_name}_currency"


####################################################################
#
def resolve_currencies(
    serializer: serializers.Serializer,
    attrs: dict,
    data: Any,
    currency: str,
) -> dict:
    """Give `attrs`' money values `currency`, and report sent mismatches.

    Walks `serializer`'s writable money fields, and the money fields of
    each item of its writable list-of-object fields, with `data` the raw
    request data those attrs were validated from.

    Args:
        serializer: The serializer `attrs` were validated by.
        attrs: The validated data; money values are replaced in place.
        data: The raw data for the same object (`initial_data` or one
            item of it).
        currency: The bank account's currency.

    Returns:
        DRF-shaped errors: `<field>_currency` for a sent currency other
        than `currency`, nested as a list for list fields.  Empty when
        every currency matches.
    """
    errors: dict[str, Any] = {}
    raw = data if hasattr(data, "get") else {}
    for name, field in serializer.fields.items():
        if field.read_only or field.source not in attrs:
            continue
        value = attrs[field.source]
        if isinstance(field, DRFMoneyField):
            if value is None:
                continue
            sent = raw.get(currency_field_name(name))
            if sent and sent != currency:
                errors[currency_field_name(name)] = [
                    f"Must be the bank account's currency, '{currency}'."
                ]
                continue
            amount = value.amount if isinstance(value, Money) else value
            attrs[field.source] = Money(amount, currency)
        elif isinstance(field, serializers.ListSerializer) and isinstance(
            field.child, serializers.Serializer
        ):
            items = raw.get(name) or []
            item_errors = [
                resolve_currencies(
                    field.child,
                    item,
                    items[i] if i < len(items) else {},
                    currency,
                )
                for i, item in enumerate(value)
            ]
            if any(item_errors):
                errors[name] = item_errors
    return errors


########################################################################
########################################################################
#
class BankAccountCurrencyMixin:
    """Resolve a serializer's money inputs to its bank account's currency.

    List it before the DRF serializer base.  A serializer that defines its
    own `validate` must call `super().validate(attrs)`.
    """

    ####################################################################
    #
    def bank_account_currency(self, attrs: dict) -> str | None:
        """The currency of the bank account `attrs` belong to.

        Returns:
            The currency, or None when it cannot be known (another
            validation error will already be reported).
        """
        raise NotImplementedError

    ####################################################################
    #
    def validate(self, attrs: dict) -> dict:
        attrs = super().validate(attrs)  # type: ignore[misc]
        currency = self.bank_account_currency(attrs)
        if currency is None:
            return attrs
        errors = resolve_currencies(
            self,
            attrs,
            self.initial_data,  # type: ignore[attr-defined]
            currency,
        )
        if errors:
            raise serializers.ValidationError(errors)
        return attrs
