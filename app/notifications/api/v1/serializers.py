# 3rd party imports
#
from rest_framework import serializers

# Project imports
#
from notifications.models import DigestFrequency


########################################################################
########################################################################
#
class NotificationPreferenceSerializer(serializers.Serializer):
    """Notification kind preference.

    Read: kind, display_name, can_suppress, enabled.
    Write (PATCH): enabled only.
    """

    kind = serializers.CharField(read_only=True)
    display_name = serializers.CharField(read_only=True)
    can_suppress = serializers.BooleanField(read_only=True)
    enabled = serializers.BooleanField()


########################################################################
########################################################################
#
class ChannelPreferenceSerializer(serializers.Serializer):
    """Channel delivery preference.

    Read: channel, display_name, digest_frequency.
    Write (PATCH): digest_frequency only.
    """

    channel = serializers.CharField(read_only=True)
    display_name = serializers.CharField(read_only=True)
    digest_frequency = serializers.ChoiceField(choices=DigestFrequency.choices)
