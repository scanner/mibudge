"""DRF serializers for the credentials API (v1)."""

# system imports
from urllib.parse import urlparse

# 3rd party imports
from rest_framework import serializers

# Project imports
from credentials.models import APIKey, Application

# Hosts that make an http:// redirect URI acceptable.  RFC 8252 section
# 7.3 carves out the loopback interface for native apps, which cannot
# terminate TLS on a callback they spin up locally.  'localhost' is
# deliberately absent -- see _validate_redirect_uri.
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1"})


####################################################################
#
def _validate_redirect_uri(uri: str) -> None:
    """Reject a redirect URI this server will not honour.

    Args:
        uri: A single redirect URI from the registration request.

    Raises:
        serializers.ValidationError: If the URI is relative, carries a
            fragment, or uses http:// for anything but an RFC 8252
            loopback address.
    """
    parsed = urlparse(uri)

    if not parsed.scheme or not parsed.hostname:
        raise serializers.ValidationError(
            f"{uri!r} is not an absolute URI with a scheme and host."
        )

    # RFC 6749 section 3.1.2: the redirect endpoint must not include a
    # fragment -- the authorization response puts its own there.
    if parsed.fragment:
        raise serializers.ValidationError(
            f"{uri!r} must not contain a fragment."
        )

    match (parsed.scheme.lower(), parsed.hostname.lower()):
        case ("https", _):
            return
        case ("http", host) if host in _LOOPBACK_HOSTS:
            return
        case ("http", "localhost"):
            # RFC 8252 section 8.3 says 'localhost' is NOT RECOMMENDED
            # (it resolves through DNS, so it is not guaranteed local),
            # and django-oauth-toolkit only grants the section 7.3
            # any-port exemption to the IP literals.  A 'localhost' URI
            # would therefore register happily and then fail at
            # authorization time for any client that binds an ephemeral
            # port -- which is most of them.  Reject it with a fix.
            raise serializers.ValidationError(
                f"{uri!r} uses 'localhost'. Use the loopback IP literal "
                "(http://127.0.0.1 or http://[::1]) instead: only those "
                "are allowed to vary the port per request, which native "
                "and MCP clients binding an ephemeral port require."
            )
        case ("http", _):
            raise serializers.ValidationError(
                f"{uri!r} uses plaintext http for a non-loopback host. "
                "Use https, or http on the loopback interface "
                "(127.0.0.1 / [::1]) for a native app."
            )
        case (scheme, _):
            raise serializers.ValidationError(
                f"{uri!r} uses the unsupported scheme {scheme!r}. "
                "Use https, or http on the loopback interface."
            )


########################################################################
########################################################################
#
class APIKeySerializer(serializers.ModelSerializer):
    """Read serializer for API keys.

    Never exposes the key material -- only the displayable prefix.  The
    plaintext key appears exactly once, in the creation response (see
    APIKeyViewSet.create).
    """

    class Meta:
        model = APIKey
        fields = [
            "uuid",
            "name",
            "prefix",
            "expires_at",
            "last_used_at",
            "revoked_at",
            "created_at",
        ]
        read_only_fields = fields


########################################################################
########################################################################
#
class APIKeyCreateSerializer(serializers.Serializer):
    """Validate an API-key creation request.

    ``expiry_days`` covers all the expiry presets (30 / 60 / 90 / 365 /
    a specific number of days); null or omitted means the key never
    expires.  The presets themselves are a UI concern.
    """

    name = serializers.CharField(max_length=100)
    expiry_days = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=1,
        max_value=3650,
    )


########################################################################
########################################################################
#
class APIKeyCreatedSerializer(APIKeySerializer):
    """Creation response -- the only place the plaintext key appears.

    Exists to document the creation response shape in the OpenAPI
    schema; the view assembles the payload itself.  ``key`` is never a
    model field and cannot be recovered after this response.
    """

    key = serializers.CharField(read_only=True)

    class Meta(APIKeySerializer.Meta):
        fields = [*APIKeySerializer.Meta.fields, "key"]
        read_only_fields = fields


########################################################################
########################################################################
#
class ApplicationSerializer(serializers.ModelSerializer):
    """Read serializer for a registered OAuth2 application.

    Never exposes ``client_secret``: it is hashed on save and cannot be
    recovered, so it appears exactly once in the creation response (see
    ApplicationCreatedSerializer).

    ``redirect_uris`` is stored by django-oauth-toolkit as one
    space-separated string; the API presents it as a list, which is what
    clients actually want to render and edit.
    """

    redirect_uris = serializers.SerializerMethodField()

    class Meta:
        model = Application
        fields = [
            "client_id",
            "name",
            "client_type",
            "redirect_uris",
            "visibility",
            "status",
            "created",
            "updated",
        ]
        read_only_fields = fields

    ####################################################################
    #
    def get_redirect_uris(self, obj: Application) -> list[str]:
        """Split the stored space-separated URIs into a list."""
        return obj.redirect_uris.split()


########################################################################
########################################################################
#
class ApplicationWriteSerializer(serializers.ModelSerializer):
    """Validate a registration or update request.

    Only ``name``, ``redirect_uris`` and (at creation) ``client_type``
    are writable.  Everything else about an application is either
    derived or a privilege the owner does not hold:

    - ``authorization_grant_type`` is pinned to authorization-code by
      the view.  It is the per-app half of the grant-type policy, so
      accepting it from input would let a caller register the implicit
      or password app the rest of the stack refuses to serve.
    - ``visibility`` and ``status`` are staff levers (promoting an app
      to global exposes it to every user), managed in the django admin.
    - ``skip_authorization`` would suppress the consent screen -- the
      one place the user is told what they are granting.
    - ``algorithm``, ``allowed_origins`` and the OIDC fields belong to
      features this server does not offer.

    ``client_type`` is create-only: switching an app between public and
    confidential changes how it authenticates at the token endpoint, and
    a confidential app's secret is only ever shown at creation.
    """

    redirect_uris = serializers.ListField(
        child=serializers.CharField(max_length=500),
        min_length=1,
        help_text=(
            "Allowed callback URIs. Must be https, or http on the "
            "loopback interface (127.0.0.1 / [::1]) for native apps."
        ),
    )

    class Meta:
        model = Application
        fields = ["name", "client_type", "redirect_uris"]
        extra_kwargs = {"name": {"required": True, "allow_blank": False}}

    ####################################################################
    #
    def validate_redirect_uris(self, value: list[str]) -> str:
        """Check every URI, then join for storage.

        Args:
            value: The submitted redirect URIs.

        Returns:
            The URIs joined into the single space-separated string the
            model stores -- the list is an API-shape convenience only.

        Raises:
            serializers.ValidationError: If any URI is unacceptable.
        """
        for uri in value:
            _validate_redirect_uri(uri)
        return " ".join(value)

    ####################################################################
    #
    def validate_client_type(self, value: str) -> str:
        """Reject a client_type change on an existing application."""
        if self.instance is not None and value != self.instance.client_type:
            raise serializers.ValidationError(
                "client_type cannot be changed after registration. "
                "Register a new application instead."
            )
        return value


########################################################################
########################################################################
#
class ApplicationCreatedSerializer(ApplicationSerializer):
    """Registration response -- the only place the secret appears.

    ``client_secret`` is returned for confidential applications only,
    and only here: it is hashed on save and unrecoverable afterwards.
    Public applications (native, mobile and MCP clients, which cannot
    keep a secret) get null -- they authenticate with PKCE instead.
    """

    client_secret = serializers.CharField(read_only=True, allow_null=True)

    class Meta(ApplicationSerializer.Meta):
        fields = [*ApplicationSerializer.Meta.fields, "client_secret"]
        read_only_fields = fields
