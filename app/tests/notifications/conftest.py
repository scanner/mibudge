from pytest_factoryboy import register

from .factories import (
    ChannelPreferenceFactory,
    NotificationFactory,
    NotificationLogFactory,
    NotificationPreferenceFactory,
)

register(NotificationLogFactory)
register(NotificationFactory)
register(NotificationPreferenceFactory)
register(ChannelPreferenceFactory)
