"""
DRF viewset for transaction categories in the moneypools v1 API.
"""

# 3rd party imports
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import (
    OpenApiResponse,
    extend_schema,
    extend_schema_view,
)
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

# Project imports
from common.views import AtomicWritesMixin
from moneypools.models import TransactionCategory

from ..filters import TransactionCategoryFilter
from ..serializers.categories import TransactionCategorySerializer


########################################################################
########################################################################
#
@extend_schema_view(
    list=extend_schema(
        summary="List transaction categories",
        description=(
            "Return the transaction categories visible to the "
            "authenticated user: the global base set, the user's own "
            "custom categories, categories owned by users they co-own "
            "a bank account with, and categories still referenced by "
            "the user's transactions after sharing ended.  Filterable "
            "by group, archived, and scope (global|mine|shared).  "
            "Searchable by group and name."
        ),
    ),
    create=extend_schema(
        summary="Create a transaction category",
        description=(
            "Create a custom category owned by the authenticated user "
            "(global categories are managed via the admin).  Group and "
            "name are whitespace-normalized; case-insensitive "
            "duplicates of global rows or the user's own rows are "
            "rejected."
        ),
    ),
    retrieve=extend_schema(
        summary="Get transaction category details",
        description="Return a single visible category by UUID.",
    ),
    update=extend_schema(
        summary="Update a transaction category",
        description=(
            "Full update of a category.  Only the owner may update; "
            "global categories are managed via the admin."
        ),
    ),
    partial_update=extend_schema(
        summary="Partially update a transaction category",
        description=(
            "Partial update of a category.  Only the owner may update; "
            "global categories are managed via the admin."
        ),
    ),
    destroy=extend_schema(
        summary="Delete a transaction category",
        description=(
            "Delete a category.  Only the owner may delete; global "
            "categories are managed via the admin.  A category still "
            "referenced by transactions or allocations cannot be "
            "deleted (409) -- archive it instead."
        ),
        responses={
            204: None,
            409: OpenApiResponse(
                description=(
                    "The category is referenced by transactions or "
                    "allocations; archive it instead."
                ),
            ),
        },
    ),
)
class TransactionCategoryViewSet(AtomicWritesMixin, viewsets.ModelViewSet):
    """Shared + per-user transaction categories.

    Visibility is computed per request via
    TransactionCategoryQuerySet.visible_to.  Mutations are owner-only;
    global rows (owner NULL) are managed exclusively through the
    django-admin.
    """

    serializer_class = TransactionCategorySerializer
    queryset = TransactionCategory.objects.all()
    lookup_field = "id"
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = TransactionCategoryFilter
    search_fields = ["group", "name"]
    ordering_fields = ["group", "name", "created_at"]
    ordering = ["group", "name"]

    ####################################################################
    #
    def get_queryset(self):
        """Restrict to categories visible to the requesting user."""
        return TransactionCategory.objects.visible_to(self.request.user)

    ####################################################################
    #
    def _require_owner(self, category: TransactionCategory) -> None:
        """Reject mutation of global rows and other users' categories.

        Raises:
            PermissionDenied: If the category is global or owned by
                someone else.
        """
        if category.owner_id is None:
            raise PermissionDenied(
                "Global categories are managed by administrators."
            )
        if category.owner_id != self.request.user.pk:
            raise PermissionDenied("Only the category's owner may modify it.")

    ####################################################################
    #
    def perform_create(self, serializer: TransactionCategorySerializer) -> None:
        """Create a category owned by the requesting user."""
        serializer.save(owner=self.request.user)

    ####################################################################
    #
    def perform_update(self, serializer: TransactionCategorySerializer) -> None:
        """Update a category after enforcing owner-only mutation."""
        self._require_owner(serializer.instance)
        serializer.save()

    ####################################################################
    #
    def destroy(
        self, request: Request, *args: object, **kwargs: object
    ) -> Response:
        """Delete a category unless it is still referenced (409)."""
        category = self.get_object()
        self._require_owner(category)
        if category.transactions.exists() or category.allocations.exists():
            return Response(
                {
                    "detail": (
                        "This category is referenced by transactions or "
                        "allocations and cannot be deleted; archive it "
                        "instead."
                    )
                },
                status=status.HTTP_409_CONFLICT,
            )
        self.perform_destroy(category)
        return Response(status=status.HTTP_204_NO_CONTENT)

    ####################################################################
    #
    @extend_schema(
        summary="Archive a transaction category",
        description=(
            "Archive a category so pickers hide it while existing "
            "references stay valid.  Only the owner may archive; "
            "global categories are managed via the admin."
        ),
        request=None,
        responses={200: TransactionCategorySerializer},
    )
    @action(detail=True, methods=["post"], url_path="archive")
    def archive(self, request: Request, id: str | None = None) -> Response:
        """Archive a category (idempotent)."""
        category = self.get_object()
        self._require_owner(category)
        if not category.archived:
            category.archived = True
            category.save(update_fields=["archived", "modified_at"])
        return Response(
            self.get_serializer(category).data, status=status.HTTP_200_OK
        )
