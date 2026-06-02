# 3rd party imports
#
from rest_framework import serializers

# Project imports
#
from notifications.models import DeliveryMode, DigestFrequency


########################################################################
########################################################################
#
class NotificationPreferenceSerializer(serializers.Serializer):
    """Notification kind preference.

    Read: kind, display_name, can_suppress, delivery_mode.
    Write (PATCH): delivery_mode only (rejected for can_suppress=False kinds).
    """

    kind = serializers.CharField(read_only=True)
    display_name = serializers.CharField(read_only=True)
    can_suppress = serializers.BooleanField(read_only=True)
    delivery_mode = serializers.ChoiceField(choices=DeliveryMode.choices)


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
