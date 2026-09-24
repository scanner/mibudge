"""
Bank-account import actions for the moneypools v1 API.

`BankAccountImportActions` holds the endpoints the importers call to
record an import, reconcile a live scrape and apply per-transaction
merchant details.  It is composed into `BankAccountViewSet`.
"""

# system imports
from datetime import date

# 3rd party imports
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

# Project imports
from moneypools.models import BankAccount, Transaction
from moneypools.service import categories as categories_svc
from moneypools.service import sync_scrape as sync_scrape_svc
from moneypools.service import transaction_details as transaction_details_svc

from ..serializers.bank_accounts import BankAccountSerializer
from ..serializers.imports import (
    ScrapeSyncReportSerializer,
    ScrapeSyncSerializer,
    TransactionDetailsReportSerializer,
    TransactionDetailsSerializer,
)


########################################################################
########################################################################
#
class BankAccountImportActions(viewsets.GenericViewSet):
    """Bank-account import actions, composed into `BankAccountViewSet`.

    Holds the endpoints the importers call against a single account:
    `mark-imported`, `sync-scrape` and `transaction-details`.  Queryset,
    lookup, serializer and permissions come from `BankAccountViewSet`.
    """

    ####################################################################
    #
    @extend_schema(
        summary="Mark import complete",
        description=(
            "Record that a transaction import has been completed for "
            "this account.  Sets last_imported_at to now and advances "
            "last_posted_through to the supplied date (never regresses "
            'an existing value).  Body: {"last_posted_through": "YYYY-MM-DD"}.'
        ),
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "last_posted_through": {"type": "string", "format": "date"}
                },
                "required": ["last_posted_through"],
            }
        },
        responses={200: BankAccountSerializer},
    )
    @action(detail=True, methods=["post"], url_path="mark-imported")
    def mark_imported(self, request: Request, id: str = "") -> Response:
        """Set last_imported_at=now and advance last_posted_through."""
        account: BankAccount = self.get_object()

        raw = request.data.get("last_posted_through")
        if not raw:
            raise ValidationError(
                {"last_posted_through": "This field is required."}
            )
        try:
            posted_through = date.fromisoformat(str(raw))
        except ValueError as exc:
            raise ValidationError(
                {"last_posted_through": "Expected YYYY-MM-DD format."}
            ) from exc

        new_posted_through = (
            max(account.last_posted_through, posted_through)
            if account.last_posted_through is not None
            else posted_through
        )

        BankAccount.objects.filter(pkid=account.pkid).update(
            last_imported_at=timezone.now(),
            last_posted_through=new_posted_through,
        )
        account.refresh_from_db()

        serializer = self.get_serializer(account)
        return Response(serializer.data)

    ####################################################################
    #
    @extend_schema(
        summary="Sync a bank-side scrape",
        description=(
            "Reconcile this account against a fresh snapshot from a "
            "live bank scraper.  All existing pending transactions on "
            "the account are deleted, posted transactions from the "
            "scrape are de-duplicated against the database, and any "
            "new posted/pending rows are inserted in the order the "
            "scraper supplies (newest-first).  Per-transaction running "
            "balance snapshots and the unallocated-budget allocation "
            "snapshots are recomputed before the request returns.  "
            "Runs atomically under the account + unallocated-budget "
            "locks; on any error the database is unchanged."
        ),
        request=ScrapeSyncSerializer,
        responses={200: ScrapeSyncReportSerializer},
    )
    @action(detail=True, methods=["post"], url_path="sync-scrape")
    def sync_scrape(self, request: Request, id: str = "") -> Response:
        """Reconcile the account against a fresh bank-side scrape."""
        account: BankAccount = self.get_object()

        serializer = ScrapeSyncSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated = serializer.validated_data

        scraped_txs = [
            sync_scrape_svc.ScrapedTransaction(
                is_pending=stx["is_pending"],
                posted_date=stx["posted_date"],
                raw_description=stx["raw_description"],
                amount=stx["amount"],
                transaction_type=stx.get("transaction_type", ""),
                running_balance=stx.get("running_balance"),
            )
            for stx in validated["transactions"]
        ]
        payload = sync_scrape_svc.ScrapeSyncPayload(
            scraped_at=validated["scraped_at"],
            ending_balance=validated["ending_balance"],
            transactions=scraped_txs,
        )

        try:
            report = sync_scrape_svc.sync_scrape(account, payload)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc

        out = ScrapeSyncReportSerializer(
            {
                "deleted_pending": report.deleted_pending,
                "inserted_posted": report.inserted_posted,
                "skipped_posted": report.skipped_posted,
                "inserted_pending": report.inserted_pending,
                "balance_mismatch": report.balance_mismatch,
                "posting_order_mismatches": report.posting_order_mismatches,
                "last_posted_through": report.last_posted_through,
                "new_transaction_ids": report.new_transaction_ids,
                "details_needed": [
                    {"index": row.index, "transaction": row.transaction_id}
                    for row in report.details_needed
                ],
            }
        )
        return Response(out.data)

    ####################################################################
    #
    @extend_schema(
        summary="Apply scraped transaction details",
        description=(
            "Apply per-transaction detail records (merchant name, "
            "location, MCC, virtual card number) fetched by a live "
            "scraper to posted transactions on this account.  Each "
            "raw details dict is stored verbatim on its transaction "
            "and the merchant columns are extracted from it.  An "
            "item's optional `category` is a mibudge category full "
            "name ('{group} : {name}') -- importers translate their "
            "provider's category vocabulary before submitting.  It "
            "seeds the transaction's category (and its unassigned "
            "allocations) when NULL; an unknown name yields a "
            "per-item warning and leaves the transaction unassigned.  "
            "The display description is recomposed on first "
            "enrichment unless the user has edited it.  Rows already "
            "enriched are skipped unless `overwrite` is true; pending "
            "rows are always skipped.  Per-item outcomes are returned "
            "in submission order."
        ),
        request=TransactionDetailsSerializer,
        responses={200: TransactionDetailsReportSerializer},
    )
    @action(detail=True, methods=["post"], url_path="transaction-details")
    def transaction_details(self, request: Request, id: str = "") -> Response:
        """Apply scraped per-transaction details to this account's rows."""
        account: BankAccount = self.get_object()

        serializer = TransactionDetailsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated = serializer.validated_data
        overwrite = validated["overwrite"]

        results = []
        counts = {
            transaction_details_svc.STATUS_APPLIED: 0,
            transaction_details_svc.STATUS_SKIPPED_HAS_DETAILS: 0,
            transaction_details_svc.STATUS_SKIPPED_PENDING: 0,
            transaction_details_svc.STATUS_NOT_FOUND: 0,
        }
        for item in validated["details"]:
            tx = Transaction.objects.filter(
                bank_account=account, id=item["transaction"]
            ).first()
            if tx is None:
                item_status = transaction_details_svc.STATUS_NOT_FOUND
                warnings: list[str] = []
            else:
                category = None
                category_warnings: list[str] = []
                category_name = item.get("category")
                if category_name:
                    category = categories_svc.find_category_for_user(
                        request.user, category_name
                    )
                    if category is None:
                        category_warnings.append(
                            f"unknown category {category_name!r}; "
                            "transaction left unassigned"
                        )
                item_status, warnings = transaction_details_svc.apply_details(
                    tx,
                    item["details"],
                    category=category,
                    overwrite=overwrite,
                )
                warnings = category_warnings + warnings
            counts[item_status] += 1
            results.append(
                {
                    "transaction": item["transaction"],
                    "status": item_status,
                    "warnings": warnings,
                }
            )

        out = TransactionDetailsReportSerializer(
            {
                "applied": counts[transaction_details_svc.STATUS_APPLIED],
                "skipped_has_details": counts[
                    transaction_details_svc.STATUS_SKIPPED_HAS_DETAILS
                ],
                "skipped_pending": counts[
                    transaction_details_svc.STATUS_SKIPPED_PENDING
                ],
                "not_found": counts[transaction_details_svc.STATUS_NOT_FOUND],
                "results": results,
            }
        )
        return Response(out.data)
