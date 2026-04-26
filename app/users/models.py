import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db.models import SET_NULL, CharField, ForeignKey, UUIDField
from django.urls import reverse
from django.utils.translation import gettext_lazy as _


def validate_timezone(value: str) -> None:
    """Raise ValidationError if value is not a valid IANA timezone name."""
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, KeyError) as exc:
        raise ValidationError(
            f"'{value}' is not a valid IANA timezone."
        ) from exc


class User(AbstractUser):
    """Default user for My Budgets."""

    # First and last name do not cover name patterns around the globe so we are
    # basically replacing "first_name" and "last_name" with just a "name"
    # field.
    #
    name = CharField(_("Name of User"), blank=True, max_length=255)

    # AbstractUser declares first_name/last_name as CharField; we remove them in
    # favour of a single name field by setting to None -- django-stubs cannot
    # represent this intentional override -- revisit if stubs improve
    #
    first_name = None  # type: ignore[assignment]
    last_name = None  # type: ignore[assignment]

    uuid = UUIDField(unique=True, default=uuid.uuid4, editable=False)

    timezone = CharField(
        max_length=100,
        default="America/Los_Angeles",
        validators=[validate_timezone],
    )

    # The account shown first on the Overview and pre-selected in the
    # account switcher.  Cleared automatically if the account is deleted.
    #
    default_bank_account = ForeignKey(
        "moneypools.BankAccount",
        null=True,
        blank=True,
        on_delete=SET_NULL,
        related_name="default_for_users",
    )

    def get_absolute_url(self):
        """Get url for user's detail view.

        Returns:
            str: URL for user detail.

        """
        return reverse("users:detail", kwargs={"username": self.username})
