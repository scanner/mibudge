"""
Check the API responses the test suite receives against `docs/openapi.yaml`.

`SchemaCheckedAPIClient` is the DRF test client the root conftest hands
out.  Every response it receives from an `/api/` path is validated
against the schema's documented response for that operation and status
code, so a view or serializer change that the schema does not reflect
fails the test that exercised it.  `make api-schema` regenerates the
schema after an API change.

A response whose status code the schema does not document (most error
responses) is not checked, and neither is a 4xx from a path or method
the API does not serve.
"""

# system imports
from functools import cache
from pathlib import Path
from typing import Any

# 3rd party imports
import yaml
from django.http import HttpResponseBase
from openapi_core import OpenAPI
from openapi_core.exceptions import OpenAPIError
from openapi_core.templating.paths.exceptions import (
    OperationNotFound,
    PathNotFound,
)
from openapi_core.templating.responses.exceptions import ResponseNotFound
from openapi_core.testing import MockRequest, MockResponse
from rest_framework.test import APIClient

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "docs" / "openapi.yaml"


####################################################################
#
def _nullable_refs(node: Any) -> None:
    """
    Rewrite drf-spectacular's nullable reference, `allOf: [<ref>]` with
    `nullable: true`, as `anyOf: [<ref>, null]` in place.

    OpenAPI 3.0 applies `nullable` only alongside a `type`, so
    validators reject `null` for the `allOf` form; the `anyOf` form
    accepts it.
    """
    match node:
        case dict():
            all_of = node.get("allOf")
            if node.get("nullable") and all_of and len(all_of) == 1:
                del node["allOf"], node["nullable"]
                node["anyOf"] = [all_of[0], {"nullable": True, "enum": [None]}]
            for value in node.values():
                _nullable_refs(value)
        case list():
            for value in node:
                _nullable_refs(value)


####################################################################
#
@cache
def openapi() -> OpenAPI:
    """The API schema, loaded once per test session."""
    with SCHEMA_PATH.open() as f:
        spec = yaml.safe_load(f)
    _nullable_refs(spec)
    return OpenAPI.from_dict(spec)


####################################################################
#
def _schema_errors(exc: BaseException) -> list[str]:
    """Flatten an openapi-core validation error into readable lines."""
    lines = [f"{type(exc).__name__}: {exc}"]
    cause = exc.__cause__
    while cause is not None:
        for err in getattr(cause, "schema_errors", None) or []:
            where = "/".join(str(p) for p in err.absolute_path) or "<body>"
            lines.append(f"  {where}: {err.message}")
        cause = cause.__cause__
    return lines


####################################################################
#
def check_response(response: HttpResponseBase) -> None:
    """
    Validate `response` against the schema's documented response.

    Raises:
        AssertionError: If the response body or content type does not
            match what the schema documents for its operation and
            status code.
    """
    request = response.wsgi_request  # type: ignore[attr-defined]
    path = request.path_info
    if not path.startswith("/api/") or response.streaming:
        return

    content_type = response.get("Content-Type") or "application/json"
    mock_request = MockRequest(
        "http://testserver", request.method.lower(), path
    )
    mock_response = MockResponse(
        response.content,  # type: ignore[attr-defined]
        status_code=response.status_code,
        content_type=content_type.split(";")[0],
    )
    try:
        openapi().validate_response(mock_request, mock_response)
    except ResponseNotFound:
        return
    except (PathNotFound, OperationNotFound) as exc:
        if response.status_code >= 400:
            return
        raise AssertionError(
            f"{request.method} {path} -> {response.status_code} is not "
            f"in {SCHEMA_PATH.name}: {exc}"
        ) from exc
    except OpenAPIError as exc:
        details = "\n".join(_schema_errors(exc))
        raise AssertionError(
            f"{request.method} {path} -> {response.status_code} does not "
            f"match {SCHEMA_PATH.name}:\n{details}"
        ) from exc


########################################################################
########################################################################
#
class SchemaCheckedAPIClient(APIClient):
    """A DRF test client that checks every API response it receives."""

    ####################################################################
    #
    def request(self, **kwargs: Any) -> HttpResponseBase:
        response = super().request(**kwargs)
        check_response(response)
        return response
