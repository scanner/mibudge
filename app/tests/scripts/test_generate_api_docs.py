#!/usr/bin/env python
#
"""Test the Markdown API reference generator."""

# 3rd party imports
import pytest
import pytest_check as check

# Project imports
from scripts.generate_api_docs import Reference, generate_markdown

REF = "#/components/schemas/"
ERROR_BODY = {"content": {"application/json": {"schema": {"$ref": f"{REF}Error"}}}}


####################################################################
#
def json_body(name: str) -> dict:
    """A JSON request or response body referring to component `name`."""
    return {"content": {"application/json": {"schema": {"$ref": f"{REF}{name}"}}}}


####################################################################
#
@pytest.fixture
def spec() -> dict:
    """A small spec: `Widget` shared by two endpoints, `Report` used once.

    `GET /widgets/{id}/` has a common 404 (marked `x-common-response`)
    and its own 409.
    """
    return {
        "info": {"title": "Test API", "version": "1"},
        "paths": {
            "/widgets/": {
                "post": {
                    "operationId": "widgets_create",
                    "tags": ["widgets"],
                    "requestBody": json_body("WidgetRequest"),
                    "responses": {"201": json_body("Widget")},
                }
            },
            "/widgets/{id}/": {
                "get": {
                    "operationId": "widgets_retrieve",
                    "tags": ["widgets"],
                    "responses": {
                        "200": json_body("Widget"),
                        "404": {
                            **ERROR_BODY,
                            "description": "No such object.",
                            "x-common-response": True,
                        },
                        "409": {**ERROR_BODY, "description": "Widget is busy."},
                    },
                }
            },
            "/report/": {
                "get": {
                    "operationId": "report_retrieve",
                    "tags": ["widgets"],
                    "responses": {"200": json_body("Report")},
                }
            },
        },
        "components": {
            "schemas": {
                "Error": {
                    "type": "object",
                    "properties": {"detail": {"type": "string"}},
                },
                "Widget": {
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "format": "uuid",
                            "readOnly": True,
                        },
                        "name": {"type": "string"},
                        "size": {"type": "integer", "nullable": True},
                    },
                },
                "WidgetRequest": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "size": {"type": "integer", "nullable": True},
                    },
                    "required": ["name"],
                },
                "Report": {
                    "type": "object",
                    "properties": {"total": {"type": "integer"}},
                },
            }
        },
    }


########################################################################
########################################################################
#
class TestGenerateMarkdown:
    """Tests for `generate_markdown`."""

    ####################################################################
    #
    def test_errors_and_objects(self, spec: dict) -> None:
        """
        GIVEN: a shared object, a single-use body, and an endpoint with a
               common and an endpoint-specific error
        WHEN:  the reference is generated
        THEN:  the common error is in the table and only listed at the
               endpoint, its own error is described there, the shared
               object is defined once and linked, the single-use body is
               inlined, and fields carry their merged flags
        """
        markdown = generate_markdown(spec)

        check.is_in(
            "| `404` | Error | No such object. |",
            markdown,
            "the common error is in the table",
        )
        check.is_in(
            "Common responses: `404`", markdown, "and listed at the endpoint"
        )
        check.is_in(
            "- **409** (Error) -- Widget is busy.",
            markdown,
            "its own error is described",
        )
        check.equal(
            markdown.count("#### Widget object"), 1, "shared object defined once"
        )
        check.is_in(
            "Send [Widget](#widget-object) -- its writable fields.",
            markdown,
            "and linked",
        )
        check.is_not_in(
            "#### Report object", markdown, "the single-use body is not an object"
        )
        check.is_in('"total": 0', markdown, "but inlined at its endpoint")
        check.is_in("// uuid · read-only", markdown, "read-only field flagged")
        check.is_in(
            "// integer | null · optional", markdown, "nullable optional field"
        )

    ####################################################################
    #
    def test_worked_example_rendered(self, spec: dict) -> None:
        """
        GIVEN: a worked example for an operation
        WHEN:  the reference is generated
        THEN:  its request is a plain json block under the endpoint
        """
        examples = {
            "widgets_create": {
                "summary": "Make a widget",
                "request": {"name": "sprocket"},
            }
        }

        markdown = generate_markdown(spec, examples)

        check.is_in("Example: Make a widget.", markdown, "the summary")
        check.is_in(
            '```json\n{\n  "name": "sprocket"\n}\n```',
            markdown,
            "the request as plain json",
        )

    ####################################################################
    #
    def test_example_for_unknown_operation_refused(self, spec: dict) -> None:
        """
        GIVEN: a worked example named after no operation
        WHEN:  the reference is generated
        THEN:  it is refused, naming the file's operation
        """
        with pytest.raises(ValueError, match="widgets_destroy"):
            generate_markdown(spec, {"widgets_destroy": {"summary": "x"}})

    ####################################################################
    #
    def test_link_to_undefined_object_refused(self, spec: dict) -> None:
        """
        GIVEN: rendered output linking an object that has no definition
        WHEN:  its links are checked
        THEN:  it is refused, naming the missing object
        """
        markdown = "#### Widget object\n\nSee [Gadget](#gadget-object).\n"

        with pytest.raises(ValueError, match="gadget-object"):
            Reference(spec, {}).check_links(markdown)
