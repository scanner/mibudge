"""
Machine credentials: long-lived keys and (phase 2) OAuth2 grants that
let services call the REST API on a user's behalf.

Moved out of the users app so that everything machines authenticate
with -- API keys, OAuth2 applications/tokens, and the future shared
scope model -- lives in one place, keeping users/ focused on identity.
"""

# system imports
import hashlib
import secrets
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

# 3rd party imports
from django.conf import settings
from django.db import models
from django.db.models import CharField, DateTimeField, ForeignKey, UUIDField
from django.utils import timezone

if TYPE_CHECKING:
    from users.models import User


########################################################################
########################################################################
#
class APIKey(models.Model):
    """A long-lived machine credential that authenticates as its owner.

    API keys let 3rd-party services (transaction importers, MCP servers,
    etc.) call the REST API on a user's behalf without holding the
    user's password.  The plaintext key is returned exactly once, at
    creation time; only a SHA-256 hash is stored.

    NOTE: We deliberately use an unsalted SHA-256 hash rather than
    Django's password hashers: the secret is a high-entropy random
    token (not a low-entropy password), so brute-forcing the digest is
    infeasible, and a deterministic hash allows an indexed O(1) lookup
    on every authenticated request.

    Keys are soft-revoked (``revoked_at``), never deleted -- rows form
    an audit trail, mirroring EmailChangeRequest and UserInvitation.

    Machine credentials are denied access to user/security endpoints
    via the RequiresInteractiveAuth permission
    (credentials/permissions.py).
    """

    # Every key starts with this literal prefix so keys are recognizable
    # in configs and secret scanners.  The stored ``prefix`` field keeps
    # the first PREFIX_DISPLAY_LENGTH chars of the plaintext so users can
    # match a key in the UI against the one they hold.
    #
    KEY_PREFIX = "mib_"
    PREFIX_DISPLAY_LENGTH = 12

    user = ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="api_keys",
    )
    uuid = UUIDField(unique=True, default=uuid.uuid4, editable=False)
    name = CharField(
        max_length=100,
        help_text="User-supplied label identifying what this key is for.",
    )
    prefix = CharField(max_length=PREFIX_DISPLAY_LENGTH, editable=False)
    hashed_key = CharField(max_length=64, unique=True, editable=False)
    # NULL expires_at means the key never expires.
    expires_at = DateTimeField(null=True, blank=True)
    # Updated on authenticated use, throttled to at most one write per
    # settings.API_KEY_LAST_USED_THROTTLE so bulk imports do not write
    # on every request.
    last_used_at = DateTimeField(null=True, blank=True)
    # Set when the expiring-key notice has been sent, so the daily
    # notify_expiring_api_keys task warns about each key exactly once.
    expiry_notified_at = DateTimeField(null=True, blank=True)
    revoked_at = DateTimeField(null=True, blank=True)
    created_at = DateTimeField(auto_now_add=True)
    modified_at = DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "API key"

    ####################################################################
    #
    def __str__(self) -> str:
        return f"{self.name} ({self.prefix}…)"

    ####################################################################
    #
    @staticmethod
    def hash_key(key: str) -> str:
        """Return the SHA-256 hex digest used to store and look up a key."""
        return hashlib.sha256(key.encode()).hexdigest()

    ####################################################################
    #
    @classmethod
    def make(
        cls,
        user: "User",
        name: str,
        expires_at: datetime | None = None,
    ) -> tuple["APIKey", str]:
        """Create a new API key for a user.

        Args:
            user: The owning user.
            name: User-supplied label for the key.
            expires_at: Expiry timestamp, or None for a non-expiring key.

        Returns:
            A tuple of (APIKey instance, plaintext key).  The plaintext
            is not stored and cannot be recovered later.
        """
        plaintext = cls.KEY_PREFIX + secrets.token_urlsafe(32)
        api_key = cls.objects.create(
            user=user,
            name=name,
            prefix=plaintext[: cls.PREFIX_DISPLAY_LENGTH],
            hashed_key=cls.hash_key(plaintext),
            expires_at=expires_at,
        )
        return api_key, plaintext

    ####################################################################
    #
    @property
    def is_expired(self) -> bool:
        """True if the key has an expiry and it has passed."""
        return self.expires_at is not None and timezone.now() > self.expires_at

    @property
    def is_revoked(self) -> bool:
        """True if the key has been revoked."""
        return self.revoked_at is not None

    @property
    def is_active(self) -> bool:
        """True if the key is neither revoked nor expired."""
        return not self.is_revoked and not self.is_expired

    ####################################################################
    #
    def revoke(self) -> None:
        """Soft-revoke the key.  Revocation is permanent."""
        self.revoked_at = timezone.now()
        self.save(update_fields=["revoked_at", "modified_at"])
