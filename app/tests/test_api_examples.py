#!/usr/bin/env python
#
"""Test the worked API examples in `examples/` against the schema."""

# system imports
import json
from pathlib import Path
from typing import Any

# 3rd party imports
import pytest
import pytest_check as check
from openapi_schema_validator import (
    OAS30ReadValidator,
    OAS30WriteValidator,
    oas30_format_checker,
)

# Project imports
from tests.openapi_contract import EXAMPLES_DIR, spec

EXAMPLE_FILES = sorted(EXAMPLES_DIR.glob("*.json"))


####################################################################
#
def operations() -> dict[str, dict]:
    """Every operation in the schema, keyed by operationId."""
    return {
        op["operationId"]: op
        for item in spec()["paths"].values()
        for method, op in item.items()
        if method != "parameters"
    }


####################################################################
#
def schema_errors(validator_cls: type, schema: dict, value: Any) -> list[str]:
    """`value`'s violations of `schema`, resolving `#/components` refs."""
    root = {**schema, "components": spec()["components"]}
    validator = validator_cls(root, format_checker=oas30_format_checker)
    return [
        f"{'/'.join(map(str, e.absolute_path)) or '<body>'}: {e.message}"
        for e in validator.iter_errors(value)
    ]


####################################################################
#
def unknown_fields(schema: dict, value: Any) -> list[str]:
    """Top-level keys of an object `value` that `schema` does not name.

    The schema allows extra properties (DRF ignores them), so a
    misspelled field in an example would otherwise pass.
    """
    ref = schema.get("$ref", "").removeprefix("#/components/schemas/")
    target = spec()["components"]["schemas"].get(ref, schema)
    known = target.get("properties")
    if not isinstance(value, dict) or known is None:
        return []
    return sorted(set(value) - set(known))


########################################################################
########################################################################
#
class TestWorkedExamples:
    """Tests for the files in `examples/`."""

    ####################################################################
    #
    @pytest.mark.parametrize("path", EXAMPLE_FILES, ids=lambda p: p.stem)
    def test_example_matches_schema(self, path: Path) -> None:
        """
        GIVEN: a worked example named after an operationId
        WHEN:  its request and response are checked against the schema
        THEN:  the operation exists, the request is a valid body for it
               naming only fields it accepts, and the response is a
               valid body for the stated status
        """
        example = json.loads(path.read_text())
        op = operations().get(path.stem)
        assert op is not None, f"no operation {path.stem!r} in the schema"

        if "request" in example:
            media = op["requestBody"]["content"]["application/json"]
            check.equal(
                schema_errors(
                    OAS30WriteValidator, media["schema"], example["request"]
                ),
                [],
                "the request is a valid body",
            )
            check.equal(
                unknown_fields(media["schema"], example["request"]),
                [],
                "naming only fields the endpoint accepts",
            )
        if "response" in example:
            response = example["response"]
            media = op["responses"][response["status"]]["content"][
                "application/json"
            ]
            check.equal(
                schema_errors(
                    OAS30ReadValidator, media["schema"], response["body"]
                ),
                [],
                "the response is a valid body",
            )
