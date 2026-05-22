# system imports
#
from typing import Any

# 3rd party imports
#
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

User = get_user_model()


########################################################################
########################################################################
#
class EmailTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    TokenObtainPairSerializer variant that uses ``email`` as the login
    field instead of ``username``.

    USERNAME_FIELD is kept as "username" so Django admin is unaffected;
    we override ``username_field`` here so simplejwt presents an ``email``
    field in the login payload and passes it to EmailBackend.authenticate().
    """

    username_field = "email"

    ####################################################################
    #
    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        # simplejwt's validate() calls authenticate(**{self.username_field: value})
        # which routes to EmailBackend because ModelBackend ignores email= kwarg.
        return super().validate(attrs)
