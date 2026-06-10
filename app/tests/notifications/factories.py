import factory
from django.contrib.auth import get_user_model
from factory.django import DjangoModelFactory

from notifications.models import (
    Channel,
    ChannelPreference,
    DeliveryMode,
    DigestFrequency,
    Notification,
    NotificationLog,
    NotificationPreference,
    NotificationPriority,
    NotificationStatus,
)

User = get_user_model()


class NotificationLogFactory(DjangoModelFactory):
    user = factory.SubFactory("tests.users.factories.UserFactory")
    channel = Channel.EMAIL
    status = NotificationStatus.PENDING

    class Meta:
        model = NotificationLog


class NotificationFactory(DjangoModelFactory):
    user = factory.SubFactory("tests.users.factories.UserFactory")
    kind = "moneypools.funding_complete"
    priority = NotificationPriority.NORMAL
    context = factory.LazyFunction(dict)
    locale = "en-us"
    channel = Channel.EMAIL
    log_entry = None

    class Meta:
        model = Notification


class NotificationPreferenceFactory(DjangoModelFactory):
    user = factory.SubFactory("tests.users.factories.UserFactory")
    kind = "moneypools.funding_complete"
    delivery_mode = DeliveryMode.DIGEST

    class Meta:
        model = NotificationPreference
        django_get_or_create = ["user", "kind"]


class ChannelPreferenceFactory(DjangoModelFactory):
    user = factory.SubFactory("tests.users.factories.UserFactory")
    channel = Channel.EMAIL
    digest_frequency = DigestFrequency.DAILY_EVENING
    last_digest_sent_at = None

    class Meta:
        model = ChannelPreference
        django_get_or_create = ["user", "channel"]
