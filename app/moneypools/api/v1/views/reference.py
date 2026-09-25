"""
DRF views for shared reference data in the moneypools v1 API.

`BankViewSet` serves the read-only bank list; `currencies` lists the
ISO 4217 currencies the system supports.
"""

# 3rd party imports
import moneyed
from django.db import transaction
from drf_spectacular.utils import (
    OpenApiResponse,
    extend_schema,
    extend_schema_view,
)
from rest_framework import viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.filters import OrderingFilter
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

# Project imports
from common.views import AtomicWritesMixin
from moneypools.models import Bank

from ..serializers.reference import BankSerializer


########################################################################
########################################################################
#
@extend_schema_view(
    list=extend_schema(
        summary="List banks",
        description=(
            "Return all banks in the system. Banks are shared reference "
            "data managed through the admin -- any authenticated user "
            "can list and retrieve them."
        ),
    ),
    retrieve=extend_schema(
        summary="Get bank details",
        description="Return a single bank by UUID.",
    ),
)
class BankViewSet(AtomicWritesMixin, viewsets.ReadOnlyModelViewSet):
    """Read-only reference data for financial institutions."""

    serializer_class = BankSerializer
    queryset = Bank.objects.all()
    lookup_field = "id"
    permission_classes = [IsAuthenticated]
    filter_backends = [OrderingFilter]
    ordering_fields = ["name"]
    ordering = ["name"]


########################################################################
########################################################################
#
@extend_schema(
    summary="List supported currencies",
    description=(
        "Return all ISO 4217 currency codes supported by the system, "
        "sorted by code. Each entry includes the code, English name, "
        "and numeric ISO 4217 code. Requires authentication."
    ),
    responses={
        200: OpenApiResponse(
            description="List of supported currencies.",
        ),
    },
)
# A read-only view: `ATOMIC_REQUESTS` would open a transaction, which
# on SQLite takes the database write lock (see
# `common.views.AtomicWritesMixin`).
#
@transaction.non_atomic_requests
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def currencies(request: Request) -> Response:
    """Return all supported ISO 4217 currencies, sorted by code."""
    data = [
        {"code": c.code, "name": c.name, "numeric": c.numeric}
        for c in sorted(moneyed.CURRENCIES.values(), key=lambda c: c.code)
    ]
    return Response(data)
