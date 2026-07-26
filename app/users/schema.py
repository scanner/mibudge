#!/usr/bin/env python
#
"""
drf-spectacular schema customization for interactive (JWT) auth.

Imported from UsersConfig.ready() -- an OpenApiAuthenticationExtension
registers itself when its class body executes, so the module has to be
imported for the override to take effect.
"""

# 3rd party imports
from drf_spectacular.contrib.rest_framework_simplejwt import SimpleJWTScheme


########################################################################
########################################################################
#
class MibudgeJWTScheme(SimpleJWTScheme):
    """drf-spectacular's simplejwt scheme, with a usable description.

    The stock extension emits only ``type``/``scheme``/``bearerFormat``,
    which tells an API consumer nothing about where to get a token or
    how long it lasts.

    NOTE: ``priority`` must be higher than the built-in extension's
    (0); both target the same authentication class and
    OpenApiGeneratorExtension.get_match() picks the highest priority.
    """

    priority = 1

    ####################################################################
    #
    def get_security_definition(self, auto_schema) -> dict:
        """Return the bearer scheme with mibudge's usage notes attached.

        Args:
            auto_schema: The drf-spectacular AutoSchema being built.

        Returns:
            The OpenAPI security scheme object.
        """
        definition = super().get_security_definition(auto_schema)
        definition["description"] = (
            "Interactive user sessions -- the SPA and native apps.\n\n"
            "POST email and password to `/api/token/` to get an access "
            "token in the response body plus a long-lived refresh token "
            "as an httpOnly cookie. Send the access token as "
            "`Authorization: Bearer <access>`; it expires after 60 "
            "minutes. `POST /api/token/refresh/` reads the refresh "
            "cookie and returns a fresh access token, rotating the "
            "cookie.\n\n"
            "This is the only credential that reaches user/security "
            "endpoints (password change, email change, invitations, "
            "API-key management); machine credentials are refused there."
        )
        return definition
