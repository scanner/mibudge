"""
Opportunistic cross-account transaction linking.

When money moves between two accounts the user owns -- a credit-card
payment from checking, a transfer from savings to a credit card, an
ACH deposit between two savings accounts -- two mirror-image
Transactions get imported, one on each side. ``Transaction`` has a
``linked_transaction`` OneToOneField specifically to pair those two
rows so the UI can surface the relationship.

This module finds and writes those links. The actual work runs in a
Celery task (``moneypools.tasks.attempt_link_transaction``) so the
request that created the Transaction does not block on the extra
queries. Pure matching logic lives here and is invoked by the task;
keeping it separate makes it directly callable from tests and from a
``relink_transactions`` management command for one-shot back-fills
after the heuristic is tuned.

Matching rules (v1):

1. Parse the new transaction's ``description`` for a hint identifying
   the *other* account. Two signals, either sufficient:

   - ``ENDING IN NNNN`` -- last four digits of ``account_number``.
   - Case-insensitive substring match against ``BankAccount.name`` or
     any entry in ``BankAccount.link_aliases``.

   The candidate account must share at least one owner with the new
   transaction's account -- no cross-user linking.

2. Inside each candidate account, look for a Transaction with:

   - ``amount == -new_tx.amount`` (opposite sign, equal magnitude)
   - ``transaction_date`` within +/- 3 days of the new transaction
   - ``linked_transaction IS NULL`` (not already paired)

3. Decide:

   - 0 matches: no link (counterpart not yet imported). Fine; the
     counterpart's own save will try again and find this row.
   - exactly 1 match: write the link on both sides.
   - 2 or more matches: refuse and warn. A wrong link is worse than
     no link.

Idempotence: if the new Transaction is already linked on entry, the
attempt is a no-op. Writes use ``update_fields`` to avoid re-firing
the balance-maintenance signals on the Transaction row.
"""

# system imports
import logging
import re
from datetime import timedelta

# 3rd party imports
from django.db import transaction as db_transaction

# Project imports
from moneypools.models import BankAccount, Transaction

logger = logging.getLogger(__name__)

# Window on either side of the new transaction's date that the
# counterpart may fall within. ACH settlement typically lands within
# 1-2 business days; 3 covers weekends and bank delays.
#
_LINK_DATE_WINDOW = timedelta(days=3)

# Matches "ENDING IN 1234" (and common variants like "ENDING ACCOUNT
# 1234"). Captured group is the last-4. Case-insensitive.
#
_ACCOUNT_SUFFIX_RE = re.compile(
    r"ENDING\s+(?:IN\s+)?(?:ACCOUNT\s+)?(\d{4})", re.IGNORECASE
)


####################################################################
#
def _candidate_accounts(tx: Transaction) -> list[BankAccount]:
    """
    Return the BankAccount(s) hinted at by ``tx.description``.

    Scans the description for a last-4 account suffix and for
    case-insensitive substring matches against every other account's
    ``name`` or ``link_aliases``. Restricts to accounts that share at
    least one owner with ``tx.bank_account`` so a transfer is only
    ever linked inside the same user's book.

    De-duplicates results so a name+alias double-hit still yields a
    single candidate.

    Args:
        tx: The newly saved Transaction to find a counterpart for.

    Returns:
        List of candidate BankAccounts, possibly empty.
    """
    description = tx.description or tx.raw_description or ""
    if not description:
        return []

    owner_ids = list(tx.bank_account.owners.values_list("id", flat=True))
    if not owner_ids:
        return []

    # Candidate pool: every other account that shares at least one owner.
    # distinct() because owners M2M can cause row multiplication.
    #
    others = (
        BankAccount.objects.filter(owners__id__in=owner_ids)
        .exclude(pkid=tx.bank_account.pkid)
        .distinct()
    )

    description_lower = description.lower()
    suffix_matches = {
        m.group(1) for m in _ACCOUNT_SUFFIX_RE.finditer(description)
    }

    candidates: dict[int, BankAccount] = {}
    for acct in others:
        hit = False

        # Substring match against name.
        if acct.name and acct.name.lower() in description_lower:
            hit = True

        # Substring match against any alias.
        if not hit and acct.link_aliases:
            for alias in acct.link_aliases:
                if alias and alias.lower() in description_lower:
                    hit = True
                    break

        # Last-4 match against account_number. EncryptedCharField
        # decrypts transparently on attribute access.
        if not hit and suffix_matches and acct.account_number:
            suffix = acct.account_number[-4:]
            if suffix in suffix_matches:
                hit = True

        if hit:
            candidates[acct.pkid] = acct

    return list(candidates.values())


####################################################################
#
def _find_counterpart(
    tx: Transaction, target: BankAccount
) -> Transaction | None:
    """
    Return the unique counterpart Transaction in ``target``, or None.

    Looks for an opposite-sign, equal-magnitude, unlinked transaction
    within the +/-3 day window. If zero or multiple matches are found
    the caller gets None; the multiple-match case logs a warning
    naming the candidates.

    Args:
        tx:     The newly saved Transaction driving the search.
        target: The candidate counterpart's BankAccount.

    Returns:
        The counterpart Transaction if exactly one matches, else None.
    """
    window_start = tx.transaction_date - _LINK_DATE_WINDOW
    window_end = tx.transaction_date + _LINK_DATE_WINDOW

    matches = list(
        Transaction.objects.filter(
            bank_account=target,
            amount=-tx.amount,
            transaction_date__gte=window_start,
            transaction_date__lte=window_end,
            linked_transaction__isnull=True,
        )
        .exclude(pkid=tx.pkid)
        .order_by("transaction_date", "pkid")[:2]
    )

    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]

    logger.warning(
        "Ambiguous link candidates for transaction %s on %s amount=%s: "
        "%d matches in account %s. Skipping link. Matches: %s",
        tx.id,
        tx.transaction_date,
        tx.amount,
        len(matches),
        target,
        [str(m.id) for m in matches],
    )
    return None


####################################################################
#
def attempt_link(tx: Transaction) -> Transaction | None:
    """
    Try to link ``tx`` to a counterpart on another account.

    Idempotent: returns the existing counterpart (without modifying
    anything) if ``tx.linked_transaction`` is already set.

    Args:
        tx: The newly saved Transaction.

    Returns:
        The counterpart Transaction if a link was established or
        already existed, else None.
    """
    if tx.linked_transaction_id is not None:
        return tx.linked_transaction

    candidates = _candidate_accounts(tx)
    if not candidates:
        return None

    for target in candidates:
        counterpart = _find_counterpart(tx, target)
        if counterpart is None:
            continue

        # Write both sides inside a single atomic block. Use
        # update_fields so pre_save on Transaction does not re-touch
        # account balances (the OneToOne FK has no bearing on money
        # invariants).
        #
        with db_transaction.atomic():
            tx.linked_transaction = counterpart
            tx.save(update_fields=["linked_transaction"])
            counterpart.linked_transaction = tx
            counterpart.save(update_fields=["linked_transaction"])

        logger.info(
            "Linked transaction %s (%s %s) to counterpart %s (%s %s).",
            tx.id,
            tx.transaction_date,
            tx.amount,
            counterpart.id,
            counterpart.transaction_date,
            counterpart.amount,
        )
        return counterpart

    return None
