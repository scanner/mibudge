"""
Shared utilities used by multiple moneypools service modules.

Keep this module free of imports from other moneypools service modules so
it can be imported by any of them without risk of circular dependencies.
"""

# 3rd party imports
#
from django.conf import settings
from django.contrib.auth import get_user_model

User = get_user_model()


########################################################################
########################################################################
#
def funding_system_user() -> User:  # type: ignore[valid-type]
    """Return the non-loginable funding-system user.

    Returns:
        The User instance with username 'funding-system'.

    Raises:
        User.DoesNotExist: If the data migration has not been run.
    """
    return User.objects.get(username=settings.FUNDING_SYSTEM_USERNAME)
