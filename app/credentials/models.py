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
from oauth2_provider.models import (
    AbstractAccessToken,
    AbstractApplication,
    AbstractGrant,
    AbstractIDToken,
    AbstractRefreshToken,
    ApplicationManager,
)

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


########################################################################
########################################################################
#
# OAuth2 provider models (django-oauth-toolkit swapped models).
#
# Why we own these models instead of using DOT's defaults:
#
#   1. Application MUST be swapped -- we add `visibility` and `status`
#      fields (below).  This is DOT's supported extension path, the same
#      mechanism as a custom AUTH_USER_MODEL.
#   2. AccessToken and RefreshToken MUST be swapped as a pair, into this
#      one app.  They share a circular foreign key
#      (AccessToken.source_refresh_token <-> RefreshToken.access_token),
#      so swapping one while leaving the other on DOT's default splits
#      that cycle across two apps and Django cannot order the migrations
#      (DOT ships the W011 system check that flags exactly this).
#   3. Grant and IDToken add no fields, but are swapped alongside them
#      because model swapping is a one-way door: it only works cleanly
#      before the first migration, on empty tables.  Doing it later, once
#      DOT's default tables hold live grants and tokens, is a painful
#      data migration.  Empty subclasses now are cheap insurance so the
#      scope work (task-mibudge-auth-scopes) can later add fields to any
#      of these models without that surgery.
#
# The token/grant subclasses inherit their abstract base's Meta so DOT's
# constraints/indexes survive, and must NOT set `swappable` (that option
# is what marks DOT's own models as the swap targets).  See
# config/settings.py for the swap wiring and the DeviceGrant decision.
#
class Application(AbstractApplication):
    """An OAuth2 client application registered against mibudge.

    Adds two fields beyond DOT's AbstractApplication:

    - `visibility`: whether the app is private to the registering user
      or promoted to global (visible/authorizable by everyone).
    - `status`: lifecycle stage gating who sees a global app, so new
      versions can be staged before every user sees them.

    Only global + published apps are listed for non-owners; earlier
    stages stay visible to the owner and staff only (enforced at the
    registration/list layer in checkpoint 4).
    """

    class Visibility(models.TextChoices):
        PRIVATE = "private", "Private to owner"
        GLOBAL = "global", "Global (all users)"

    class Status(models.TextChoices):
        TESTING = "testing", "Testing"
        VALIDATION = "validation", "Validation"
        PUBLISHED = "published", "Published"

    # NOTE: the var-annotated ignores below are unavoidable, not sloppy:
    # DOT ships no type stubs, so django-stubs sees AbstractApplication as
    # Any and does not treat Application as a Django model -- it therefore
    # cannot infer the descriptor type for fields we add here (inherited
    # fields are unaffected, being declared on the untyped base).  The
    # fields are ordinary CharFields at runtime.
    visibility = models.CharField(  # type: ignore[var-annotated]
        max_length=16,
        choices=Visibility.choices,
        default=Visibility.PRIVATE,
        help_text=(
            "Private apps are visible only to the registering user; "
            "global apps are visible to all users (staff-promoted)."
        ),
    )
    status = models.CharField(  # type: ignore[var-annotated]
        max_length=16,
        choices=Status.choices,
        default=Status.TESTING,
        help_text=(
            "Lifecycle stage.  Only global + published apps are listed "
            "for non-owners; earlier stages are owner/staff only."
        ),
    )

    objects = ApplicationManager()

    class Meta(AbstractApplication.Meta):
        pass

    ####################################################################
    #
    def natural_key(self) -> tuple[str]:
        """Natural key (client_id) for serialization/fixtures."""
        return (self.client_id,)


class Grant(AbstractGrant):
    """Authorization-code grant (short-lived, exchanged for a token)."""

    class Meta(AbstractGrant.Meta):
        pass


class AccessToken(AbstractAccessToken):
    """A bearer access token issued to an authorized application."""

    class Meta(AbstractAccessToken.Meta):
        pass


class RefreshToken(AbstractRefreshToken):
    """A refresh token used to mint a new access token on rotation."""

    class Meta(AbstractRefreshToken.Meta):
        pass


class IDToken(AbstractIDToken):
    """An OpenID Connect ID token (kept swapped for FK integrity)."""

    class Meta(AbstractIDToken.Meta):
        pass
