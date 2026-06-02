"""Tests for the notifications DRF API views."""

# system imports
#
from collections.abc import Callable

# 3rd party imports
#
import pytest

# app imports
#
from notifications.models import (
    ChannelPreference,
    DeliveryMode,
    DigestFrequency,
    NotificationPreference,
)
from rest_framework.test import APIClient

from users.models import User

pytestmark = pytest.mark.django_db

# Suppressible kind present in the registry (moneypools app).
_SUPPRESSIBLE_KIND = "moneypools.funding_complete"
# Non-suppressible kind (security notification; can_suppress=False).
_LOCKED_KIND = "users.password_changed"


########################################################################
########################################################################
#
@pytest.mark.parametrize(
    "url",
    [
        pytest.param(
            "/api/v1/notification-preferences/", id="notification-preferences"
        ),
        pytest.param("/api/v1/channel-preferences/", id="channel-preferences"),
    ],
)
def test_endpoints_require_auth(url: str) -> None:
    """
    GIVEN: an unauthenticated client
    WHEN:  a list endpoint is accessed
    THEN:  401 is returned
    """
    assert APIClient().get(url).status_code == 401


########################################################################
########################################################################
#
@pytest.mark.parametrize(
    "list_url,create_pref,lookup_key,lookup_val,value_field,expected_default",
    [
        pytest.param(
            "/api/v1/notification-preferences/",
            lambda user: NotificationPreference.objects.create(
                user=user,
                kind=_SUPPRESSIBLE_KIND,
                delivery_mode=DeliveryMode.OFF,
            ),
            "kind",
            _SUPPRESSIBLE_KIND,
            "delivery_mode",
            DeliveryMode.DIGEST,
            id="notification-preferences",
        ),
        pytest.param(
            "/api/v1/channel-preferences/",
            lambda user: ChannelPreference.objects.create(
                user=user,
                channel="email",
                digest_frequency=DigestFrequency.TWICE_DAILY,
            ),
            "channel",
            "email",
            "digest_frequency",
            DigestFrequency.DAILY_EVENING,
            id="channel-preferences",
        ),
    ],
)
def test_list_user_isolation(
    user_factory: Callable[..., User],
    list_url: str,
    create_pref: Callable,
    lookup_key: str,
    lookup_val: str,
    value_field: str,
    expected_default: object,
) -> None:
    """
    GIVEN: user A has a stored preference; user B has none
    WHEN:  user B fetches the list
    THEN:  the item shows the default, not user A's stored value
    """
    user_a = user_factory()
    user_b = user_factory()
    create_pref(user_a)
    client = APIClient()
    client.force_authenticate(user=user_b)
    response = client.get(list_url)

    item = next(p for p in response.data if p[lookup_key] == lookup_val)
    assert item[value_field] == expected_default


########################################################################
########################################################################
#
class TestNotificationPreferenceAPI:
    """Tests for GET/PATCH /api/v1/notification-preferences/."""

    LIST_URL = "/api/v1/notification-preferences/"

    ####################################################################
    #
    @pytest.mark.parametrize(
        "kind,stored_mode,expected_mode",
        [
            # No DB row -- falls through to registry default_delivery_mode.
            pytest.param(
                _SUPPRESSIBLE_KIND,
                None,
                DeliveryMode.DIGEST,
                id="no-row-default-digest",
            ),
            pytest.param(
                "moneypools.import_complete",
                None,
                DeliveryMode.OFF,
                id="no-row-default-off",
            ),
            # Stored preference overrides the registry default.
            pytest.param(
                _SUPPRESSIBLE_KIND,
                DeliveryMode.OFF,
                DeliveryMode.OFF,
                id="db-row-off-overrides-default",
            ),
            pytest.param(
                _SUPPRESSIBLE_KIND,
                DeliveryMode.IMMEDIATE,
                DeliveryMode.IMMEDIATE,
                id="db-row-immediate",
            ),
        ],
    )
    def test_list_delivery_mode(
        self,
        user_factory: Callable[..., User],
        notification_preference_factory: Callable[..., NotificationPreference],
        kind: str,
        stored_mode: str | None,
        expected_mode: str,
    ) -> None:
        """
        GIVEN: an authenticated user with or without a stored preference
        WHEN:  the list endpoint is called
        THEN:  the kind's delivery_mode matches the stored value or the
               registry default_delivery_mode when no row exists
        """
        user = user_factory()
        if stored_mode is not None:
            notification_preference_factory(
                user=user, kind=kind, delivery_mode=stored_mode
            )
        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get(self.LIST_URL)

        assert response.status_code == 200
        pref = next(p for p in response.data if p["kind"] == kind)
        assert pref["delivery_mode"] == expected_mode

    ####################################################################
    #
    @pytest.mark.parametrize(
        "delivery_mode",
        [
            pytest.param(DeliveryMode.OFF, id="off"),
            pytest.param(DeliveryMode.IMMEDIATE, id="immediate"),
            pytest.param(DeliveryMode.DIGEST, id="digest"),
        ],
    )
    def test_patch_suppressible_kind(
        self,
        user_factory: Callable[..., User],
        delivery_mode: str,
    ) -> None:
        """
        GIVEN: an authenticated user
        WHEN:  a PATCH with a valid delivery_mode is sent for a suppressible kind
        THEN:  200 is returned, the DB row is upserted, and the response
               reflects the new value
        """
        user = user_factory()
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.patch(
            f"{self.LIST_URL}{_SUPPRESSIBLE_KIND}/",
            {"delivery_mode": delivery_mode},
            format="json",
        )

        assert response.status_code == 200
        assert response.data["delivery_mode"] == delivery_mode
        assert (
            NotificationPreference.objects.get(
                user=user, kind=_SUPPRESSIBLE_KIND
            ).delivery_mode
            == delivery_mode
        )

    ####################################################################
    #
    @pytest.mark.parametrize(
        "kind,expected_status,expected_key",
        [
            pytest.param("unknown.kind", 404, None, id="unknown-kind"),
            pytest.param(
                _LOCKED_KIND, 400, "detail", id="non-suppressible-kind"
            ),
        ],
    )
    def test_patch_invalid(
        self,
        user_factory: Callable[..., User],
        kind: str,
        expected_status: int,
        expected_key: str | None,
    ) -> None:
        """
        GIVEN: an authenticated user
        WHEN:  a PATCH targets an unknown or non-suppressible kind
        THEN:  the expected error status is returned
        """
        user = user_factory()
        client = APIClient()
        client.force_authenticate(user=user)
        response = client.patch(
            f"{self.LIST_URL}{kind}/",
            {"delivery_mode": DeliveryMode.OFF},
            format="json",
        )

        assert response.status_code == expected_status
        if expected_key is not None:
            assert expected_key in response.data


########################################################################
########################################################################
#
class TestChannelPreferenceAPI:
    """Tests for GET/PATCH /api/v1/channel-preferences/."""

    LIST_URL = "/api/v1/channel-preferences/"

    ####################################################################
    #
    def test_list_returns_all_channels(
        self, user_factory: Callable[..., User]
    ) -> None:
        """
        GIVEN: an authenticated user
        WHEN:  the list endpoint is called
        THEN:  all Channel values appear in the response
        """
        user = user_factory()
        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get(self.LIST_URL)

        assert response.status_code == 200
        assert {"email", "push"} <= {p["channel"] for p in response.data}

    ####################################################################
    #
    @pytest.mark.parametrize(
        "stored_frequency,expected_frequency",
        [
            pytest.param(
                None,
                DigestFrequency.DAILY_EVENING,
                id="no-row-defaults-to-daily-evening",
            ),
            pytest.param(
                DigestFrequency.WEEKLY_FRIDAY,
                DigestFrequency.WEEKLY_FRIDAY,
                id="stored-frequency-returned",
            ),
        ],
    )
    def test_list_email_frequency(
        self,
        user_factory: Callable[..., User],
        channel_preference_factory: Callable[..., ChannelPreference],
        stored_frequency: str | None,
        expected_frequency: str,
    ) -> None:
        """
        GIVEN: an authenticated user with or without a stored channel preference
        WHEN:  the list endpoint is called
        THEN:  the email channel shows the stored frequency or DAILY_EVENING
               when no row exists
        """
        user = user_factory()
        if stored_frequency is not None:
            channel_preference_factory(
                user=user, channel="email", digest_frequency=stored_frequency
            )
        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get(self.LIST_URL)

        email_pref = next(p for p in response.data if p["channel"] == "email")
        assert email_pref["digest_frequency"] == expected_frequency

    ####################################################################
    #
    def test_patch_updates_digest_frequency(
        self, user_factory: Callable[..., User]
    ) -> None:
        """
        GIVEN: an authenticated user
        WHEN:  a PATCH with a valid digest_frequency is sent for email
        THEN:  200 is returned, the DB row is upserted, and the response
               reflects the new value
        """
        user = user_factory()
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.patch(
            f"{self.LIST_URL}email/",
            {"digest_frequency": DigestFrequency.TWICE_DAILY},
            format="json",
        )

        assert response.status_code == 200
        assert response.data["digest_frequency"] == DigestFrequency.TWICE_DAILY
        assert (
            ChannelPreference.objects.get(
                user=user, channel="email"
            ).digest_frequency
            == DigestFrequency.TWICE_DAILY
        )

    ####################################################################
    #
    @pytest.mark.parametrize(
        "channel,payload,expected_status,expected_key",
        [
            pytest.param(
                "notachannel",
                {"digest_frequency": DigestFrequency.DAILY_EVENING},
                404,
                None,
                id="unknown-channel",
            ),
            pytest.param(
                "email",
                {"digest_frequency": "never"},
                400,
                "digest_frequency",
                id="invalid-frequency",
            ),
        ],
    )
    def test_patch_invalid(
        self,
        user_factory: Callable[..., User],
        channel: str,
        payload: dict,
        expected_status: int,
        expected_key: str | None,
    ) -> None:
        """
        GIVEN: an authenticated user
        WHEN:  a PATCH targets an unknown channel or supplies an invalid frequency
        THEN:  the expected error status is returned
        """
        user = user_factory()
        client = APIClient()
        client.force_authenticate(user=user)
        response = client.patch(
            f"{self.LIST_URL}{channel}/", payload, format="json"
        )

        assert response.status_code == expected_status
        if expected_key is not None:
            assert expected_key in response.data
