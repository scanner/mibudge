# system imports
#
import secrets


####################################################################
#
def generate_token() -> str:
    """Return a cryptographically secure URL-safe token (64-char string).

    Used as the default for invitation and email-change token fields.
    """
    return secrets.token_urlsafe(48)
