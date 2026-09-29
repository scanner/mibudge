"""
OpenAPI schema generation: the error responses every endpoint declares.

`AutoSchema` (the project's `DEFAULT_SCHEMA_CLASS`) adds to each
operation the error statuses its view can return by construction, and
leaves any status a view's `@extend_schema(responses=...)` already
declares alone:

- 400 `ValidationError`: a write with a request body, or a list GET
  with `DjangoFilterBackend` (an invalid filter value).
- 401 `Error`: any view that authenticates (a bad credential fails
  before the permission check, even on an AllowAny view).
- 403 `Error`: a view whose permission classes deny some authenticated
  callers (staff-only, interactive-credential-only).
- 404 `Error`: a detail route (the object lookup), or a paginated
  list (a page past the end).
- 429 `Error`: any throttled view.

A view declares the other errors it returns itself, with
`error_response` / `validation_error_response`.

Error bodies are DRF's: `{"detail": "..."}` (`Error`) for everything
but validation, and for validation a map of field name to messages, or
a bare list of messages when a view raises `ValidationError("...")`
(`ValidationError`).
"""

# system imports
from typing import Any

# 3rd party imports
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.extensions import OpenApiSerializerExtension
from drf_spectacular.openapi import AutoSchema as SpectacularAutoSchema
from drf_spectacular.utils import OpenApiResponse
from rest_framework import serializers
from rest_framework.permissions import SAFE_METHODS, IsAdminUser

# Project imports
from users.permissions import (
    RequiresInteractiveAuth,
    RequiresInteractiveAuthForWrites,
)


########################################################################
########################################################################
#
class ErrorSerializer(serializers.Serializer):
    """DRF's error body for everything but a validation failure."""

    detail = serializers.CharField(help_text="Human-readable reason.")
    code = serializers.CharField(
        required=False, help_text="Machine-readable reason, when given."
    )


########################################################################
########################################################################
#
class ValidationErrorSerializer(serializers.Serializer):
    """DRF's validation error body; its schema is `ValidationErrorExtension`."""


########################################################################
########################################################################
#
class ValidationErrorExtension(OpenApiSerializerExtension):
    """Describe `ValidationErrorSerializer` as DRF's validation body.

    A field-keyed map (`non_field_errors` for errors not tied to one
    field) whose values are a message, a list of messages, a list of
    per-item error maps (`many=True` fields) or a nested map; or a
    bare list of messages.
    """

    target_class = ValidationErrorSerializer

    ####################################################################
    #
    def map_serializer(self, auto_schema: Any, direction: Any) -> dict:
        return {
            "anyOf": [
                {
                    "type": "object",
                    "additionalProperties": {
                        "anyOf": [
                            {"type": "string"},
                            {"type": "array", "items": {}},
                            {"type": "object"},
                        ]
                    },
                },
                {"type": "array", "items": {"type": "string"}},
            ],
            "description": (
                "Field name to messages (`non_field_errors` for errors "
                "not tied to one field), or a list of messages."
            ),
        }


####################################################################
#
def error_response(description: str) -> OpenApiResponse:
    """An error response with an `Error` (`{"detail": ...}`) body."""
    return OpenApiResponse(response=ErrorSerializer, description=description)


####################################################################
#
def validation_error_response(description: str) -> OpenApiResponse:
    """An error response with a `ValidationError` body."""
    return OpenApiResponse(
        response=ValidationErrorSerializer, description=description
    )


########################################################################
########################################################################
#
class AutoSchema(SpectacularAutoSchema):
    """drf-spectacular's `AutoSchema` plus each view's generic errors."""

    ####################################################################
    #
    def _get_response_bodies(self, direction: Any = "response") -> dict:
        responses = super()._get_response_bodies(direction)
        if direction != "response":
            return responses
        for code, (serializer, description) in self._default_errors().items():
            if code not in responses:
                responses[code] = self._get_response_for_code(
                    OpenApiResponse(
                        response=serializer, description=description
                    ),
                    code,
                    direction=direction,
                )
        return responses

    ####################################################################
    #
    def _default_errors(self) -> dict[str, tuple[type, str]]:
        """The error statuses this operation's view returns by construction."""
        view = self.view
        permissions = view.get_permissions()
        errors: dict[str, tuple[type, str]] = {}

        writes = self.method in ("POST", "PUT", "PATCH")
        filtered_list = self.method == "GET" and any(
            issubclass(backend, DjangoFilterBackend)
            for backend in getattr(view, "filter_backends", [])
        )
        if (writes and self.get_request_serializer() is not None) or (
            filtered_list and self._is_list_view()
        ):
            errors["400"] = (ValidationErrorSerializer, "Invalid input.")

        # Authentication runs before the permission check, so a bad
        # credential is a 401 even on an AllowAny view.
        #
        if view.get_authenticators():
            errors["401"] = (
                ErrorSerializer,
                "Missing or invalid credentials.",
            )

        denies = any(
            isinstance(p, (IsAdminUser, RequiresInteractiveAuth))
            and not (
                isinstance(p, RequiresInteractiveAuthForWrites)
                and self.method in SAFE_METHODS
            )
            for p in permissions
        )
        if denies:
            errors["403"] = (
                ErrorSerializer,
                "The credentials are not allowed to do this.",
            )

        if getattr(view, "detail", False):
            errors["404"] = (ErrorSerializer, "No such object.")
        elif (
            self.method == "GET"
            and self._is_list_view()
            and self._get_paginator()
        ):
            errors["404"] = (ErrorSerializer, "Invalid page.")

        if view.get_throttles():
            errors["429"] = (ErrorSerializer, "Too many requests.")

        return errors
