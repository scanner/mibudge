"""
REST API client for the mibudge service.

Supports two authentication modes:

- **API key** (preferred): a long-lived machine credential sent as
  ``Authorization: Api-Key <key>``.  Create one at Settings -> API keys
  in the SPA (or POST /api/v1/users/me/api-keys/).
- **Email/password JWT** (legacy): obtains a JWT access token from
  POST /api/token/ and re-authenticates automatically on expiry.

Handles transparent pagination for list endpoints and 429 throttling.

Example usage::

    with MibudgeClient("http://localhost:8000", api_key="mib_...") as client:
        for tx in client.get_all("/api/v1/transactions/", {"bank_account": uuid}):
            print(tx["id"])
"""

# system imports
import logging
import re
import time
from collections.abc import Iterator
from typing import Any

# 3rd party imports
import httpx

logger = logging.getLogger(__name__)


########################################################################
########################################################################
#
class AuthenticationError(Exception):
    """Raised when the server rejects the supplied credentials."""


########################################################################
########################################################################
#
class APIError(Exception):
    """Raised for non-2xx responses from the API after any retry."""

    ####################################################################
    #
    def __init__(self, response: httpx.Response) -> None:
        self.response = response
        super().__init__(
            f"API error {response.status_code}: {response.text[:200]}"
        )


####################################################################
#
def _parse_retry_after(resp: httpx.Response) -> float | None:
    """
    Extract the retry delay in seconds from a 429 response.

    Prefers the standard ``Retry-After`` header (DRF sets it to a
    decimal number of seconds). Falls back to scraping DRF's default
    body message ``"Expected available in N seconds."`` so we still
    recover if a reverse proxy strips the header.

    Returns:
        Delay in seconds, or None if no value could be parsed.
    """
    header = resp.headers.get("Retry-After")
    if header is not None:
        try:
            return float(header)
        except ValueError:
            pass
    try:
        body = resp.json()
    except ValueError:
        return None
    detail = body.get("detail", "") if isinstance(body, dict) else ""
    match = re.search(r"available in (\d+)\s*seconds?", detail)
    if match:
        return float(match.group(1))
    return None


########################################################################
########################################################################
#
class MibudgeClient:
    """
    HTTP client for the mibudge REST API.

    With *api_key* set, every request carries ``Authorization: Api-Key
    <key>`` and no login round-trip is needed; a 401 means the key is
    invalid/revoked/expired and raises AuthenticationError immediately.

    With *email*/*password*, authenticates via POST /api/token/ and
    stores a JWT access token in memory.  On a 401 response the client
    re-authenticates once and retries the request automatically -- this
    covers the normal token-expiry case without embedding expiry-time
    logic.

    Implements the context-manager protocol so it can be used with
    ``with``:  the underlying connection pool is closed on exit.

    Args:
        base_url: Root URL of the mibudge service, e.g.
            'http://localhost:8000'.  Trailing slash is stripped.
        email: Account email address (JWT mode).
        password: Account password (JWT mode).
        api_key: mibudge API key (machine-credential mode).  Mutually
            exclusive with email/password; takes precedence if both
            are supplied.
        timeout: Per-request timeout in seconds (default 30).
        verify: TLS verification setting forwarded to httpx. Pass a
            path to a PEM bundle (e.g. mkcert's rootCA.pem) to trust
            locally-issued certificates; pass False to disable
            verification (not recommended); leave as None to use
            httpx's default (system CAs).
        max_throttle_wait: Maximum seconds to sleep in response to a
            429 Retry-After before giving up and raising APIError. A
            server that asks for a wait longer than this is treated as
            "abort the import" rather than silently stalling.
    """

    ####################################################################
    #
    def __init__(
        self,
        base_url: str,
        email: str | None = None,
        password: str | None = None,
        *,
        api_key: str | None = None,
        timeout: float = 30.0,
        verify: bool | str | None = None,
        max_throttle_wait: float = 60.0,
    ) -> None:
        if api_key is None and (email is None or password is None):
            raise ValueError(
                "Either api_key or both email and password are required."
            )
        self._base_url = base_url.rstrip("/")
        self._email = email
        self._password = password
        self._api_key = api_key
        self._access_token: str | None = None
        self._max_throttle_wait = max_throttle_wait
        # httpx treats verify=True as "use system CAs". Pass a path to
        # trust an additional CA bundle (e.g. mkcert's rootCA.pem for
        # local HTTPS development).
        client_kwargs: dict[str, Any] = {"timeout": timeout}
        if verify is not None:
            client_kwargs["verify"] = verify
        self._http = httpx.Client(**client_kwargs)

    ####################################################################
    #
    def authenticate(self) -> None:
        """
        Obtain a fresh JWT access token from the API.

        A no-op in API-key mode: keys are stateless credentials sent on
        every request, so there is nothing to obtain.

        Raises:
            AuthenticationError: If the server returns 401 (bad credentials).
            httpx.HTTPError: For network-level failures.
        """
        if self._api_key is not None:
            return
        resp = self._http.post(
            f"{self._base_url}/api/token/",
            json={"email": self._email, "password": self._password},
        )
        if resp.status_code == 401:
            raise AuthenticationError(
                f"Authentication failed for user {self._email!r}."
            )
        resp.raise_for_status()
        self._access_token = resp.json()["access"]
        logger.debug("Authenticated as %r", self._email)

    ####################################################################
    #
    def _auth_headers(self) -> dict[str, str]:
        """Return Authorization header dict, authenticating first if needed."""
        if self._api_key is not None:
            return {"Authorization": f"Api-Key {self._api_key}"}
        if self._access_token is None:
            self.authenticate()
        return {"Authorization": f"Bearer {self._access_token}"}

    ####################################################################
    #
    def _request(
        self,
        method: str,
        url_or_path: str,
        *,
        retry_on_401: bool = True,
        **kwargs: Any,
    ) -> httpx.Response:
        """
        Make an authenticated HTTP request.

        Accepts either an absolute URL (starts with 'http') or a path
        (e.g. '/api/v1/transactions/').  On a 401 the client re-authenticates
        once and retries.

        Args:
            method: HTTP method ('GET', 'POST', 'PATCH', etc.).
            url_or_path: Absolute URL or root-relative path.
            retry_on_401: Re-authenticate and retry once on 401.
            **kwargs: Forwarded to httpx.Client.request.

        Returns:
            The httpx.Response on success (2xx).

        Raises:
            APIError: For non-2xx responses after any retry.
        """
        url = (
            url_or_path
            if url_or_path.startswith("http")
            else f"{self._base_url}{url_or_path}"
        )
        resp = self._http.request(
            method, url, headers=self._auth_headers(), **kwargs
        )
        if resp.status_code == 401:
            # An API key never expires mid-run the way a JWT does; a 401
            # means it is invalid, revoked, or expired -- retrying with
            # the same key cannot succeed.
            if self._api_key is not None:
                raise AuthenticationError(
                    "The API key was rejected (invalid, revoked, or "
                    "expired). Create a new key at Settings -> API keys."
                )
            if retry_on_401:
                logger.debug("Received 401; re-authenticating and retrying.")
                self.authenticate()
                resp = self._http.request(
                    method, url, headers=self._auth_headers(), **kwargs
                )
        if resp.status_code == 429:
            resp = self._handle_throttled(resp, method, url, **kwargs)
        if not resp.is_success:
            raise APIError(resp)
        return resp

    ####################################################################
    #
    def _handle_throttled(
        self,
        resp: httpx.Response,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> httpx.Response:
        """
        Honor a 429 response by sleeping per Retry-After and retrying.

        DRF's throttling sets the Retry-After header to the number of
        seconds until the quota refills. We also fall back to parsing
        the JSON body's 'Expected available in N seconds.' message if
        the header is absent. A wait above *max_throttle_wait* is
        treated as "abort": we return the 429 unchanged so the caller
        raises APIError and the import can fail fast.

        Returns:
            The response from the retry, or the original 429 if the
            wait exceeds the configured ceiling.
        """
        wait = _parse_retry_after(resp)
        if wait is None or wait > self._max_throttle_wait:
            logger.warning(
                "Throttled (429); Retry-After=%s exceeds max wait %.0fs. "
                "Not retrying.",
                wait,
                self._max_throttle_wait,
            )
            return resp
        logger.info("Throttled (429); sleeping %.1fs then retrying.", wait)
        time.sleep(wait)
        return self._http.request(
            method, url, headers=self._auth_headers(), **kwargs
        )

    ####################################################################
    #
    def get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """
        GET a single URL and return the parsed JSON body.

        Args:
            path: Root-relative path (e.g. '/api/v1/bank-accounts/').
            params: Optional query parameters.

        Returns:
            The parsed JSON response body.
        """
        return self._request("GET", path, params=params).json()

    ####################################################################
    #
    def get_all(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        page_size: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        """
        Iterate over every item in a paginated list endpoint.

        Follows DRF's 'next' cursor across pages automatically.  The
        'results' key is expected on every page response; if absent, an
        empty sequence is assumed (e.g. a non-paginated response).

        The server enforces a maximum page size (currently 500); if
        *page_size* exceeds that, the server silently caps it.

        Args:
            path: Root-relative path (e.g. '/api/v1/transactions/').
            params: Query parameters sent with the first request; not
                repeated on subsequent pages because DRF embeds them in
                the 'next' URL.
            page_size: Optional page size override.  Defaults to the
                server's default (100) when not specified.

        Yields:
            Each item dict from the 'results' list, across all pages.
        """
        query: dict[str, Any] = dict(params or {})
        if page_size is not None:
            query["page_size"] = page_size

        url: str | None = path
        first = True
        while url is not None:
            data = self._request(
                "GET",
                url,
                params=query if first else None,
            ).json()
            first = False
            yield from data.get("results", [])
            url = data.get("next")

    ####################################################################
    #
    def post(
        self,
        path: str,
        json: dict[str, Any],
    ) -> dict[str, Any]:
        """
        POST a JSON body and return the parsed response.

        Args:
            path: Root-relative path.
            json: Request body.

        Returns:
            The parsed JSON response body.
        """
        return self._request("POST", path, json=json).json()

    ####################################################################
    #
    def patch(
        self,
        path: str,
        json: dict[str, Any],
    ) -> dict[str, Any]:
        """
        PATCH a JSON body and return the parsed response.

        Args:
            path: Root-relative path (e.g. '/api/v1/transactions/<id>/').
            json: Fields to update.

        Returns:
            The parsed JSON response body.
        """
        return self._request("PATCH", path, json=json).json()

    ####################################################################
    #
    def close(self) -> None:
        """Close the underlying connection pool."""
        self._http.close()

    ####################################################################
    #
    def __enter__(self) -> "MibudgeClient":
        return self

    ####################################################################
    #
    def __exit__(self, *args: Any) -> None:
        self.close()
