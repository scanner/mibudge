"""
Request middleware shared across the project.

`ClientAddressMiddleware` sets `REMOTE_ADDR` to the client's address as
reported by the reverse proxies this deployment trusts.
"""

# system imports
#
from collections.abc import Callable

# 3rd party imports
#
from django.conf import settings
from django.http import HttpRequest, HttpResponseBase


########################################################################
########################################################################
#
def client_address(xff: str | None, trusted_proxies: int) -> str | None:
    """
    Pick the client's address out of an `X-Forwarded-For` header.

    Each proxy appends the address it received the request from, so the
    last `trusted_proxies` entries were written by our own proxies and
    the entry `trusted_proxies` from the end is the client that
    connected to the outermost one.  Entries to the left of it are
    whatever the client sent and are ignored.  A chain shorter than
    `trusted_proxies` yields its leftmost entry, the way DRF's
    `NUM_PROXIES` handling does.

    Args:
        xff: The raw `X-Forwarded-For` header value, if present.
        trusted_proxies: How many reverse proxies front the app.

    Returns:
        The client's address, or None when there is nothing to trust
        (no proxies, or no header).
    """
    if trusted_proxies <= 0 or not xff:
        return None
    addrs = [addr.strip() for addr in xff.split(",")]
    return addrs[-min(trusted_proxies, len(addrs))] or None


########################################################################
########################################################################
#
class ClientAddressMiddleware:
    """
    Set `REMOTE_ADDR` from `X-Forwarded-For` using `TRUSTED_PROXY_COUNT`.

    Everything that identifies a client by address -- DRF's anonymous
    throttle (`NUM_PROXIES = 0`), allauth's rate limits, logging --
    reads `REMOTE_ADDR`, so the address is resolved once, here.  It
    comes first in `MIDDLEWARE`.
    """

    ####################################################################
    #
    def __init__(
        self, get_response: Callable[[HttpRequest], HttpResponseBase]
    ) -> None:
        self.get_response = get_response

    ####################################################################
    #
    def __call__(self, request: HttpRequest) -> HttpResponseBase:
        addr = client_address(
            request.META.get("HTTP_X_FORWARDED_FOR"),
            settings.TRUSTED_PROXY_COUNT,
        )
        if addr:
            request.META["REMOTE_ADDR"] = addr
        return self.get_response(request)
