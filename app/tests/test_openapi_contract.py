#!/usr/bin/env python
#
"""Test the OpenAPI response check the test clients run."""

# 3rd party imports
import pytest
import yaml
from django.http import JsonResponse
from django.test import RequestFactory

# Project imports
from tests.openapi_contract import SCHEMA_PATH, check_response


########################################################################
########################################################################
#
class TestCheckResponse:
    """Tests for `check_response`."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "status,body",
        [
            (200, {"count": 0, "next": None, "previous": None, "results": []}),
            (401, {"detail": "Authentication credentials were not provided."}),
        ],
    )
    def test_accepts_documented_response(
        self, rf: RequestFactory, status: int, body: dict
    ) -> None:
        """
        GIVEN: a response to `GET /api/v1/banks/` with a documented status
               and a body matching its schema
        WHEN:  it is checked against the schema
        THEN:  the check passes
        """
        response = JsonResponse(body, status=status)
        response.wsgi_request = rf.get("/api/v1/banks/")  # type: ignore[attr-defined]

        check_response(response)

    ####################################################################
    #
    @pytest.mark.parametrize(
        "status,body,reason",
        [
            (200, {"banks": []}, "does not match"),
            (418, {"detail": "teapot"}, "status is not documented"),
        ],
    )
    def test_rejects_undocumented_response(
        self, rf: RequestFactory, status: int, body: dict, reason: str
    ) -> None:
        """
        GIVEN: a response to `GET /api/v1/banks/` whose body does not
               match its schema, or whose status is not documented
        WHEN:  it is checked against the schema
        THEN:  the check fails, naming the operation and the reason
        """
        response = JsonResponse(body, status=status)
        response.wsgi_request = rf.get("/api/v1/banks/")  # type: ignore[attr-defined]

        with pytest.raises(AssertionError, match=reason):
            check_response(response)


########################################################################
########################################################################
#
class TestSchemaErrorResponses:
    """Tests for the error responses `docs/openapi.yaml` declares."""

    ####################################################################
    #
    def test_every_error_response_has_an_error_body(self) -> None:
        """
        GIVEN: the generated schema
        WHEN:  every 4xx and 5xx response it declares is inspected
        THEN:  each has a JSON body that is an `Error` or a
               `ValidationError`
        """
        with SCHEMA_PATH.open() as f:
            spec = yaml.safe_load(f)
        bodies = {
            "#/components/schemas/Error",
            "#/components/schemas/ValidationError",
        }

        offenders = [
            f"{method.upper()} {path} {code}"
            for path, item in spec["paths"].items()
            for method, operation in item.items()
            if method != "parameters"
            for code, response in operation["responses"].items()
            if code[0] in "45"
            and response.get("content", {})
            .get("application/json", {})
            .get("schema", {})
            .get("$ref")
            not in bodies
        ]

        assert offenders == []
