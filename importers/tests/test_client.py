"""Tests for the mibudge REST API client."""

# system imports
import json
from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock

# 3rd party imports
import httpx
import pytest
from pytest_mock import MockerFixture

# Project imports
from importers.client import APIError, AuthenticationError, MibudgeClient


########################################################################
########################################################################
#
def _make_response(
    status_code: int,
    body: Any = None,
    *,
    method: str = "GET",
    url: str = "http://testserver/api/v1/test/",
) -> httpx.Response:
    """Build a minimal httpx.Response for use in tests."""
    content = json.dumps(body).encode() if body is not None else b""
    return httpx.Response(
        status_code=status_code,
        content=content,
        headers={"content-type": "application/json"},
        request=httpx.Request(method, url),
    )


########################################################################
########################################################################
#
class TestAuthentication:
    """Tests for MibudgeClient authentication."""

    ####################################################################
    #
    def test_authenticate_stores_access_token(
        self,
        client: MibudgeClient,
        mock_auth: Callable[..., MagicMock],
    ) -> None:
        """
        GIVEN: valid credentials
        WHEN:  authenticate() is called
        THEN:  the access token is stored on the client
        """
        mock_auth(client, access="token-abc")
        client.authenticate()
        assert client._access_token == "token-abc"

    ####################################################################
    #
    def test_authenticate_raises_on_401(
        self,
        client: MibudgeClient,
        mock_auth: Callable[..., MagicMock],
    ) -> None:
        """
        GIVEN: invalid credentials
        WHEN:  authenticate() is called
        THEN:  AuthenticationError is raised
        """
        mock_auth(client, status=401)
        with pytest.raises(AuthenticationError, match="user"):
            client.authenticate()

    ####################################################################
    #
    def test_authenticate_called_lazily_on_first_request(
        self,
        client: MibudgeClient,
        mock_auth: Callable[..., MagicMock],
        mocker: MockerFixture,
    ) -> None:
        """
        GIVEN: a client that has not yet authenticated
        WHEN:  get() is called without a prior authenticate() call
        THEN:  authenticate() is called transparently before the request
        """
        mock_auth(client, access="lazy-token")
        mocker.patch.object(
            client._http,
            "request",
            return_value=_make_response(
                200, {"count": 0, "next": None, "results": []}
            ),
        )
        assert client._access_token is None
        client.get("/api/v1/bank-accounts/")
        assert client._access_token == "lazy-token"


########################################################################
########################################################################
#
class TestAutoReauth:
    """Tests for automatic re-authentication on 401."""

    ####################################################################
    #
    def test_reauth_on_401_retries_request(
        self,
        client: MibudgeClient,
        mock_auth: Callable[..., MagicMock],
        mocker: MockerFixture,
    ) -> None:
        """
        GIVEN: a client whose token has expired (server returns 401)
        WHEN:  get() is called
        THEN:  the client re-authenticates and retries, returning the
               successful second response
        """
        client._access_token = "stale-token"
        mock_auth(client, access="new-token")
        mocker.patch.object(
            client._http,
            "request",
            side_effect=[
                _make_response(401, {"detail": "token expired"}),
                _make_response(200, {"count": 0, "next": None, "results": []}),
            ],
        )
        result = client.get("/api/v1/bank-accounts/")
        assert result["count"] == 0
        assert client._access_token == "new-token"

    ####################################################################
    #
    def test_api_error_raised_when_retry_also_fails(
        self,
        client: MibudgeClient,
        mock_auth: Callable[..., MagicMock],
        mocker: MockerFixture,
    ) -> None:
        """
        GIVEN: an endpoint that returns 401 even after re-authentication
        WHEN:  get() is called
        THEN:  APIError is raised
        """
        client._access_token = "token"
        mock_auth(client)
        mocker.patch.object(
            client._http,
            "request",
            return_value=_make_response(401, {"detail": "forbidden"}),
        )
        with pytest.raises(APIError) as exc_info:
            client.get("/api/v1/bank-accounts/")
        assert exc_info.value.response.status_code == 401


########################################################################
########################################################################
#
class TestGetAll:
    """Tests for MibudgeClient.get_all() pagination."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "pages,expected_ids",
        [
            ([{"count": 0, "next": None, "results": []}], []),
            (
                [
                    {
                        "count": 3,
                        "next": "http://testserver/api/v1/transactions/?page=2",
                        "results": [{"id": "1"}, {"id": "2"}],
                    },
                    {"count": 3, "next": None, "results": [{"id": "3"}]},
                ],
                ["1", "2", "3"],
            ),
        ],
        ids=["empty", "two-pages"],
    )
    def test_get_all_collects_all_pages(
        self,
        pages: list[dict[str, Any]],
        expected_ids: list[str],
        client: MibudgeClient,
        mocker: MockerFixture,
    ) -> None:
        """
        GIVEN: a paginated endpoint returning N pages
        WHEN:  get_all() is called
        THEN:  all items across all pages are yielded in order
        """
        client._access_token = "t"
        mocker.patch.object(
            client._http,
            "request",
            side_effect=[_make_response(200, page) for page in pages],
        )
        results = list(client.get_all("/api/v1/transactions/"))
        assert [r["id"] for r in results] == expected_ids

    ####################################################################
    #
    def test_get_all_passes_params_on_first_page_only(
        self,
        client: MibudgeClient,
        mocker: MockerFixture,
    ) -> None:
        """
        GIVEN: get_all() called with filter params and a two-page result
        WHEN:  the first page includes a 'next' URL
        THEN:  params are sent on the first call only; the second call
               uses the 'next' URL with no extra params
        """
        client._access_token = "t"
        mock_request = mocker.patch.object(
            client._http,
            "request",
            side_effect=[
                _make_response(
                    200,
                    {
                        "count": 2,
                        "next": "http://testserver/api/v1/transactions/?bank_account=abc&page=2",
                        "results": [{"id": "1"}],
                    },
                ),
                _make_response(
                    200,
                    {"count": 2, "next": None, "results": [{"id": "2"}]},
                ),
            ],
        )
        results = list(
            client.get_all("/api/v1/transactions/", {"bank_account": "abc"})
        )
        assert [r["id"] for r in results] == ["1", "2"]
        first_kwargs = mock_request.call_args_list[0].kwargs
        second_kwargs = mock_request.call_args_list[1].kwargs
        assert first_kwargs.get("params") == {"bank_account": "abc"}
        assert second_kwargs.get("params") is None

    ####################################################################
    #
    def test_get_all_includes_page_size_in_first_request(
        self,
        client: MibudgeClient,
        mocker: MockerFixture,
    ) -> None:
        """
        GIVEN: get_all() called with page_size=500
        WHEN:  the request is made
        THEN:  page_size is included in the first request's params
        """
        client._access_token = "t"
        mock_request = mocker.patch.object(
            client._http,
            "request",
            return_value=_make_response(
                200, {"count": 1, "next": None, "results": [{"id": "1"}]}
            ),
        )
        list(
            client.get_all(
                "/api/v1/transactions/",
                {"bank_account": "abc"},
                page_size=500,
            )
        )
        first_kwargs = mock_request.call_args_list[0].kwargs
        assert first_kwargs.get("params") == {
            "bank_account": "abc",
            "page_size": 500,
        }


########################################################################
########################################################################
#
class TestPostAndPatch:
    """Tests for MibudgeClient.post() and patch()."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "method_name,expected_http_method,path,payload",
        [
            (
                "post",
                "POST",
                "/api/v1/transactions/",
                {"amount": "10.00", "bank_account": "uuid-abc"},
            ),
            (
                "patch",
                "PATCH",
                "/api/v1/transactions/uuid-abc/",
                {"pending": False},
            ),
        ],
        ids=["post", "patch"],
    )
    def test_method_sends_json_and_returns_response(
        self,
        method_name: str,
        expected_http_method: str,
        path: str,
        payload: dict[str, Any],
        client: MibudgeClient,
        mocker: MockerFixture,
    ) -> None:
        """
        GIVEN: a valid API path and JSON payload
        WHEN:  post() or patch() is called
        THEN:  the payload is forwarded and the response body is returned
        """
        returned_body = {"id": "uuid-abc", **payload}
        client._access_token = "t"
        mock_request = mocker.patch.object(
            client._http,
            "request",
            return_value=_make_response(200, returned_body),
        )
        result = getattr(client, method_name)(path, payload)
        assert result["id"] == "uuid-abc"
        mock_request.assert_called_once_with(
            expected_http_method,
            f"http://testserver{path}",
            headers={"Authorization": "Bearer t"},
            json=payload,
        )

    ####################################################################
    #
    def test_api_error_raised_for_400_on_post(
        self,
        client: MibudgeClient,
        mocker: MockerFixture,
    ) -> None:
        """
        GIVEN: a POST endpoint that returns 400 Bad Request
        WHEN:  post() is called
        THEN:  APIError is raised with the response attached
        """
        client._access_token = "t"
        mocker.patch.object(
            client._http,
            "request",
            return_value=_make_response(
                400, {"amount": ["This field is required."]}
            ),
        )
        with pytest.raises(APIError) as exc_info:
            client.post("/api/v1/transactions/", {})
        assert exc_info.value.response.status_code == 400


########################################################################
########################################################################
#
class TestContextManager:
    """Tests for MibudgeClient used as a context manager."""

    ####################################################################
    #
    def test_close_called_on_exit(
        self,
        client: MibudgeClient,
        mocker: MockerFixture,
    ) -> None:
        """
        GIVEN: a client used as a context manager
        WHEN:  the with-block exits normally
        THEN:  close() is called on the underlying HTTP client
        """
        mock_close = mocker.patch.object(client._http, "close")
        with client:
            pass
        mock_close.assert_called_once()
