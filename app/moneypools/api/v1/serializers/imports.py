"""
Serializers for the bank-account import actions in the moneypools v1 API.

The `ScrapeSync*` serializers carry the request and report of the
`sync-scrape` action; the `TransactionDetails*` serializers carry the
request and report of the `transaction-details` action.  Both actions
live on `BankAccountImportActions` in `moneypools.api.v1.views.imports`.
"""

# 3rd party imports
from djmoney.contrib.django_rest_framework import MoneyField as DRFMoneyField
from rest_framework import serializers

# Project imports
from moneypools.models import DECIMAL_PLACES, MAX_DIGITS, get_default_currency


########################################################################
########################################################################
#
class ScrapeSyncTransactionSerializer(serializers.Serializer):
    """One transaction in a scrape-sync payload.

    Mirrors `service.sync_scrape.ScrapedTransaction`.  Pending rows
    carry the scrape's local `posted_date` (banks typically render
    pending rows without a real settlement date -- e.g. BofA shows
    'Processing' in the date column -- and the scraper substitutes
    the current local datetime).  Posted rows carry the bank-supplied
    settlement datetime.  `transaction_date` is derived server-side
    from the embedded MM/DD pattern in `raw_description`.

    `running_balance` is optional and used only for the posting-order
    sanity walk; never persisted.
    """

    is_pending = serializers.BooleanField()
    posted_date = serializers.DateTimeField()
    raw_description = serializers.CharField(max_length=512)
    amount = DRFMoneyField(
        max_digits=MAX_DIGITS,
        decimal_places=DECIMAL_PLACES,
        default_currency=get_default_currency(),
    )
    transaction_type = serializers.CharField(
        max_length=32, required=False, allow_blank=True, default=""
    )
    running_balance = serializers.DecimalField(
        max_digits=MAX_DIGITS,
        decimal_places=DECIMAL_PLACES,
        required=False,
        allow_null=True,
        default=None,
    )


########################################################################
########################################################################
#
class ScrapeSyncSerializer(serializers.Serializer):
    """Input serializer for the bank-account scrape-sync action.

    Validates a full bank-side snapshot for one account: when the
    scrape was taken, the bank's ending available balance, and the
    list of transactions (newest-first as the bank renders them).
    """

    scraped_at = serializers.DateTimeField()
    ending_balance = DRFMoneyField(
        max_digits=MAX_DIGITS,
        decimal_places=DECIMAL_PLACES,
        default_currency=get_default_currency(),
    )
    transactions = ScrapeSyncTransactionSerializer(many=True)


########################################################################
########################################################################
#
class ScrapeSyncDetailsNeededSerializer(serializers.Serializer):
    """One posted scrape row still needing a transaction-details fetch.

    `index` is the row's position in the SUBMITTED transactions array
    (exact correlation back to the scraper's own rows); `transaction`
    is the DB row the fetched details should be applied to via the
    transaction-details action.
    """

    index = serializers.IntegerField()
    transaction = serializers.UUIDField()


########################################################################
########################################################################
#
class ScrapeSyncReportSerializer(serializers.Serializer):
    """Output serializer for the bank-account scrape-sync action.

    Mirrors `service.sync_scrape.ScrapeSyncReport`.  Reports
    everything the caller needs to summarise what changed and surface
    validation warnings.
    """

    deleted_pending = serializers.IntegerField()
    inserted_posted = serializers.IntegerField()
    skipped_posted = serializers.IntegerField()
    inserted_pending = serializers.IntegerField()
    balance_mismatch = serializers.DecimalField(
        max_digits=MAX_DIGITS,
        decimal_places=DECIMAL_PLACES,
        allow_null=True,
    )
    posting_order_mismatches = serializers.ListField(
        child=serializers.CharField()
    )
    last_posted_through = serializers.DateField(allow_null=True)
    new_transaction_ids = serializers.ListField(child=serializers.UUIDField())
    details_needed = ScrapeSyncDetailsNeededSerializer(many=True)


########################################################################
########################################################################
#
class TransactionDetailsItemSerializer(serializers.Serializer):
    """One (transaction, raw details dict) pair to apply.

    The details dict is stored verbatim on the transaction (it is the
    provenance record); the service extracts the merchant columns from
    it.  `category` is a mibudge category full name ('{group} :
    {name}') -- the IMPORTER translates its provider's vocabulary
    before submitting; mibudge carries no provider mappings.  The name
    is resolved case-insensitively among the categories visible to the
    caller; an unknown name yields a per-item warning and the
    transaction stays unassigned.
    """

    transaction = serializers.UUIDField()
    details = serializers.DictField()
    category = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        default=None,
        max_length=140,
    )


########################################################################
########################################################################
#
class TransactionDetailsSerializer(serializers.Serializer):
    """Input serializer for the bank-account transaction-details action.

    `overwrite` re-applies scraper-owned fields on rows already
    enriched (location fields and an assigned category are still
    never clobbered).
    """

    overwrite = serializers.BooleanField(default=False)
    details = TransactionDetailsItemSerializer(many=True)


########################################################################
########################################################################
#
class TransactionDetailsResultSerializer(serializers.Serializer):
    """Per-item outcome of the transaction-details action."""

    transaction = serializers.UUIDField()
    status = serializers.ChoiceField(
        choices=[
            "applied",
            "skipped_has_details",
            "skipped_pending",
            "not_found",
        ]
    )
    warnings = serializers.ListField(child=serializers.CharField())


########################################################################
########################################################################
#
class TransactionDetailsReportSerializer(serializers.Serializer):
    """Output serializer for the bank-account transaction-details action."""

    applied = serializers.IntegerField()
    skipped_has_details = serializers.IntegerField()
    skipped_pending = serializers.IntegerField()
    not_found = serializers.IntegerField()
    results = TransactionDetailsResultSerializer(many=True)
