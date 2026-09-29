#!/usr/bin/env python
#
"""Test the OpenAPI response check the test clients run."""

# 3rd party imports
import pytest
from django.http import JsonResponse
from django.test import RequestFactory

# Project imports
from tests.openapi_contract import check_response


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
            (418, {"banks": []}),
        ],
    )
    def test_accepts_matching_or_undocumented(
        self, rf: RequestFactory, status: int, body: dict
    ) -> None:
        """
        GIVEN: a response to `GET /api/v1/banks/` that matches its
               documented page schema, or has an undocumented status
        WHEN:  it is checked against the schema
        THEN:  the check passes
        """
        response = JsonResponse(body, status=status)
        response.wsgi_request = rf.get("/api/v1/banks/")  # type: ignore[attr-defined]

        check_response(response)

    ####################################################################
    #
    def test_rejects_mismatched_body(self, rf: RequestFactory) -> None:
        """
        GIVEN: a 200 response to `GET /api/v1/banks/` that is not a page
        WHEN:  it is checked against the schema
        THEN:  the check fails, naming the operation
        """
        response = JsonResponse({"banks": []})
        response.wsgi_request = rf.get("/api/v1/banks/")  # type: ignore[attr-defined]

        with pytest.raises(AssertionError, match="GET /api/v1/banks/ -> 200"):
            check_response(response)
