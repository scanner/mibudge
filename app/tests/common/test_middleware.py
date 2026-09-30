#!/usr/bin/env python
#
"""Test the client address resolved from X-Forwarded-For."""

# system imports
#
from collections.abc import Iterator

# 3rd party imports
#
import pytest
from django.core.cache import cache
from django.urls import reverse
from pytest_django.fixtures import SettingsWrapper
from pytest_mock import MockerFixture
from rest_framework.test import APIClient
from rest_framework.throttling import AnonRateThrottle

# Project imports
#
from common.middleware import client_address


########################################################################
########################################################################
#
class TestClientAddress:
    """Tests for picking the client out of an X-Forwarded-For chain."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "xff,trusted_proxies,expected",
        [
            ("1.1.1.1, 10.0.0.1", 0, None),
            (None, 2, None),
            ("1.1.1.1, 10.0.0.1, 172.17.0.1", 2, "10.0.0.1"),
            ("6.6.6.6, 1.1.1.1, 10.0.0.1, 172.17.0.1", 3, "1.1.1.1"),
            ("10.0.0.1, 172.17.0.1", 3, "10.0.0.1"),
        ],
        ids=[
            "no-proxies-ignores-header",
            "no-header",
            "picks-nth-from-end",
            "ignores-client-supplied-prefix",
            "short-chain-takes-leftmost",
        ],
    )
    def test_client_address(
        self, xff: str | None, trusted_proxies: int, expected: str | None
    ) -> None:
        """
        GIVEN: an X-Forwarded-For value and a trusted proxy count
        WHEN:  the client address is resolved
        THEN:  it is the entry that many from the end, clamped to the
               leftmost, or None when nothing is trusted
        """
        assert client_address(xff, trusted_proxies) == expected


########################################################################
########################################################################
#
@pytest.fixture
def one_anon_request_per_hour(
    settings: SettingsWrapper, mocker: MockerFixture
) -> Iterator[None]:
    """Three trusted proxies and an anonymous rate of one request.

    `AnonRateThrottle.THROTTLE_RATES` is bound when DRF's settings are
    first read, so the rate is patched on the class.  The throttle
    history lives in the default cache, cleared around the test.
    """
    settings.TRUSTED_PROXY_COUNT = 3
    mocker.patch.object(AnonRateThrottle, "THROTTLE_RATES", {"anon": "1/hour"})
    cache.clear()
    yield
    cache.clear()


########################################################################
########################################################################
#
@pytest.mark.django_db
class TestAnonThrottleIdent:
    """Tests for the anonymous throttle bucket behind trusted proxies."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "first_xff,second_xff,second_status",
        [
            (
                "1.1.1.1, 10.0.0.1, 172.17.0.1",
                "6.6.6.6, 1.1.1.1, 10.0.0.1, 172.17.0.1",
                429,
            ),
            (
                "1.1.1.1, 10.0.0.1, 172.17.0.1",
                "2.2.2.2, 10.0.0.1, 172.17.0.1",
                404,
            ),
        ],
        ids=["spoofed-prefix-shares-bucket", "other-client-own-bucket"],
    )
    def test_anon_bucket_keyed_on_client(
        self,
        one_anon_request_per_hour: None,
        api_client: APIClient,
        first_xff: str,
        second_xff: str,
        second_status: int,
    ) -> None:
        """
        GIVEN: an anonymous rate of one request per hour behind three
               proxies, and a first request that used it up
        WHEN:  a second request arrives through the same proxies
        THEN:  it is throttled when it comes from the same client,
               whatever it put in front of the chain, and served when
               it comes from another client
        """
        url = reverse("api_v1:invitation-detail", kwargs={"token": "nope"})

        first = api_client.get(url, HTTP_X_FORWARDED_FOR=first_xff)
        assert first.status_code == 404
        second = api_client.get(url, HTTP_X_FORWARDED_FOR=second_xff)

        assert second.status_code == second_status
