import uuid
from datetime import timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import (
    SET_NULL,
    CharField,
    DateTimeField,
    EmailField,
    ForeignKey,
    PositiveSmallIntegerField,
    UUIDField,
)
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from common.tokens import generate_token


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

    # Override AbstractUser's email to make it unique and required.
    # This is the primary login credential for the SPA; username is kept for
    # Django admin access only.
    #
    email = EmailField(_("email address"), unique=True)

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


########################################################################
########################################################################
#
class EmailChangeRequest(models.Model):
    """Tracks a pending or completed self-service email-address change.

    Lifecycle:
      - Created when the user submits a new address.  Sends a
        verification link to the new address and a revoke-link
        notification to the old address.
      - Confirmed when the new-address recipient clicks the link.
        ``confirmed_at`` and ``revocable_until`` are set; ``User.email``
        is updated.
      - Revoked when the old-address recipient clicks 'this wasn't me'
        within the revocation window.  ``revoked_at`` is set; ``User.email``
        is reverted and all sessions are invalidated.

    Rows are never deleted (they form an audit trail).
    """

    user = ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="email_change_requests",
    )
    old_email = EmailField()
    new_email = EmailField()
    token = CharField(max_length=64, unique=True, default=generate_token)
    expires_at = DateTimeField()
    confirmed_at = DateTimeField(null=True, blank=True)
    # Set to confirmed_at + EMAIL_CHANGE_REVOCATION_DAYS when confirmed.
    revocable_until = DateTimeField(null=True, blank=True)
    revoked_at = DateTimeField(null=True, blank=True)
    created_at = DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    ####################################################################
    #
    @property
    def is_expired(self) -> bool:
        """True if the verification link has passed its expiry."""
        return timezone.now() > self.expires_at

    @property
    def is_confirmed(self) -> bool:
        """True if the new address has been verified."""
        return self.confirmed_at is not None

    @property
    def is_revoked(self) -> bool:
        """True if the request has been cancelled via 'this wasn't me'."""
        return self.revoked_at is not None

    @property
    def is_revocable(self) -> bool:
        """True if the revoke link is still valid.

        Pre-confirmation: always revocable (token expiry does not block
        revocation -- the user should be able to cancel even a stale
        pending request).
        Post-confirmation: revocable until ``revocable_until``.
        """
        if self.revoked_at is not None:
            return False
        if self.confirmed_at is None:
            return True
        return (
            self.revocable_until is not None
            and timezone.now() < self.revocable_until
        )

    ####################################################################
    #
    @classmethod
    def active_revocation_window(
        cls, user: "User"
    ) -> "EmailChangeRequest | None":
        """Return the confirmed request still within its revocation window, or None."""
        return cls.objects.filter(
            user=user,
            confirmed_at__isnull=False,
            revoked_at__isnull=True,
            revocable_until__gt=timezone.now(),
        ).first()

    ####################################################################
    #
    @classmethod
    def make(cls, user: "User", new_email: str) -> "EmailChangeRequest":
        """Create a new request, setting expiry from settings."""
        return cls.objects.create(
            user=user,
            old_email=user.email,
            new_email=new_email,
            expires_at=timezone.now()
            + timedelta(hours=settings.EMAIL_CHANGE_TOKEN_EXPIRY_HOURS),
        )

    ####################################################################
    #
    def confirm(self) -> None:
        """Mark confirmed and open the revocation window. Caller saves the user."""
        now = timezone.now()
        self.confirmed_at = now
        self.revocable_until = now + timedelta(
            days=settings.EMAIL_CHANGE_REVOCATION_DAYS
        )
        self.save(update_fields=["confirmed_at", "revocable_until"])

    ####################################################################
    #
    def revoke(self) -> None:
        """Mark revoked. Caller handles user revert and session kill."""
        self.revoked_at = timezone.now()
        self.save(update_fields=["revoked_at"])


########################################################################
########################################################################
#
class UserInvitation(models.Model):
    """Tracks a staff-initiated invitation for a brand-new mibudge user.

    A staff admin invites someone by email address.  If the address is
    already registered the invitation is rejected at creation time.  On
    acceptance the invitee's account is activated and an allauth
    password-reset link is emailed so they can set their first password.

    Lifecycle:
      - pending:   invitation sent; invitee has not yet acted.
      - accepted:  invitee accepted; account activated, password-reset sent.
      - expired:   token TTL elapsed with no action.

    Rows are never deleted (audit trail).
    """

    ####################################################################
    #
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACCEPTED = "accepted", "Accepted"
        CANCELLED = "cancelled", "Cancelled"
        EXPIRED = "expired", "Expired"

    #
    ####################################################################

    invited_by = ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sent_user_invitations",
    )
    invitee_email = EmailField(
        help_text="Email address the invitation was sent to. Immutable after creation.",
        editable=False,
    )
    # Populated at creation time via get_or_create_inactive_user().
    # May be NULL if the user record is later deleted (SET_NULL).
    invitee_user = ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="received_user_invitations",
    )
    token = CharField(
        max_length=64,
        unique=True,
        default=generate_token,
        editable=False,
    )
    status = CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
    )
    expires_at = DateTimeField()
    accepted_at = DateTimeField(null=True, blank=True)
    cancelled_at = DateTimeField(null=True, blank=True)
    # Resend tracking: how many times the invitation email has been sent
    # (starts at 1 for the initial send) and when it was last sent.
    send_count = PositiveSmallIntegerField(default=1)
    last_sent_at = DateTimeField(default=timezone.now)
    created_at = DateTimeField(auto_now_add=True)
    modified_at = DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    ####################################################################
    #
    @property
    def is_expired(self) -> bool:
        """True if the invitation token has passed its expiry."""
        return timezone.now() > self.expires_at

    @property
    def is_pending(self) -> bool:
        """True if the invitation is still awaiting a response."""
        return self.status == self.Status.PENDING

    @property
    def is_terminal(self) -> bool:
        """True if the invitation has reached a final state."""
        return self.status in (
            self.Status.ACCEPTED,
            self.Status.CANCELLED,
            self.Status.EXPIRED,
        )

    ####################################################################
    #
    @classmethod
    def make(
        cls,
        invited_by: "User",
        invitee_email: str,
        invitee_user: "User | None",
    ) -> "UserInvitation":
        """Create a new pending invitation with a pre-computed expiry."""
        expiry_days = settings.INVITATION_EXPIRY_DAYS
        return cls.objects.create(
            invited_by=invited_by,
            invitee_email=invitee_email,
            invitee_user=invitee_user,
            expires_at=timezone.now() + timedelta(days=expiry_days),
        )

    ####################################################################
    #
    @classmethod
    def pending_for_token(cls, token: str) -> "UserInvitation | None":
        """Return the pending invitation for the given token, or None."""
        return (
            cls.objects.filter(token=token, status=cls.Status.PENDING)
            .select_related("invited_by", "invitee_user")
            .first()
        )
