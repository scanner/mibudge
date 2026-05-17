"""
Verify the core balance invariants for every BankAccount.

Three levels of checks are applied:

  1. Account level -- sum(budget.balance) == available_balance
     Every dollar in a BankAccount is accounted for by exactly one Budget.
     Budget balances track available_balance (pending transactions reduce
     both), so the comparison uses available_balance, not posted_balance.
     The service layer (transaction_allocation.create/update_amount/delete
     and internal_transaction.create/delete) maintains this invariant
     atomically on every operation.  Bulk writes (bulk_create/bulk_update)
     bypass the service layer and are a common source of drift.

  2. Transaction level -- sum(allocation.amount) == transaction.amount
     Every cent of a Transaction is distributed across one or more
     TransactionAllocations.  The service layer enforces this on every
     allocation create/update/delete.

  3. Budget running-balance chain -- for each Budget, the sequence of
     stored balance snapshots on its TransactionAllocations
     (budget_balance) and InternalTransactions (src_budget_balance /
     dst_budget_balance) is internally consistent, and the final
     snapshot matches budget.balance.

     Events are ordered by the same timeline used by the service layer:
     InternalTransactions at timestamp T precede TransactionAllocations
     at timestamp T; created_at breaks ties within an event type.

     Note: the chain check derives its initial balance from the current
     budget.balance, so it can verify internal snapshot consistency but
     cannot independently confirm that budget.balance itself is correct.
     The account-level check is the absolute anchor for that.

This command is read-only: it never mutates data.  The intended fix
workflow on a mismatch is:

  1. Identify the offending account / budget / transaction from the output.
  2. Run ``recompute_running_balances`` to rebuild balance snapshots.
  3. Re-run ``verify_balances`` to confirm the fix.

Usage:

    uv run python app/manage.py verify_balances
    uv run python app/manage.py verify_balances --account <uuid>
    uv run python app/manage.py verify_balances --tolerance 0.01

Exits non-zero when any check fails so the command can be wired into CI
or a periodic Celery health-check task.
"""

# system imports
#
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

# 3rd party imports
#
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Sum

# Project imports
#
from moneypools.management.commands._budget_admin import resolve_account
from moneypools.models import (
    BankAccount,
    Budget,
    InternalTransaction,
    Transaction,
    TransactionAllocation,
)


########################################################################
########################################################################
#
def _check_goal_invariant(
    budget: Budget,
    tolerance: Decimal,
) -> str | None:
    """
    Verify the Goal funded_amount invariant: balance == funded_amount + spent_amount.

    Allocation amounts follow the credit/debit convention used throughout the
    service layer: positive = credit to the budget (deposit or refund), negative
    = debit from the budget (expense).  TransactionAllocationService.create does
    ``budget.balance += amount``, so:

        balance = funded_amount + sum(allocation amounts)

    Note the ``+`` not ``-``: expenses are *negative* allocation amounts, so
    adding them reduces the balance as expected.

    spent_amount is the raw signed sum of all TransactionAllocation amounts
    against this budget.  Returns an error string on failure, None on pass.
    """
    spent = Decimal(
        TransactionAllocation.objects.filter(budget=budget).aggregate(
            total=Sum("amount")
        )["total"]
        or 0
    )
    # + not - : expenses are negative allocation amounts, so adding them
    # reduces the expected balance.  TransactionAllocationService.create
    # does ``budget.balance += amount``, so the invariant is additive.
    expected_balance = (budget.funded_amount.amount + spent).quantize(
        Decimal("0.01")
    )
    actual_balance = budget.balance.amount.quantize(Decimal("0.01"))
    if abs(expected_balance - actual_balance) > tolerance:
        return (
            f"    Goal invariant violated: "
            f"funded_amount={budget.funded_amount.amount}"
            f"  spent={spent}"
            f"  expected_balance={expected_balance}"
            f"  actual_balance={actual_balance}"
            f"  off_by={actual_balance - expected_balance:+.2f}"
        )
    return None


########################################################################
########################################################################
#
@dataclass
class _Event:
    """One balance-changing event in a budget's running-balance chain."""

    # Comparable tuple: (timestamp, kind, ...) where kind=0 for
    # InternalTransactions (precede allocations at the same timestamp)
    # and kind=1 for TransactionAllocations.
    sort_key: tuple
    delta: Decimal  # signed balance change (+credit / -debit)
    snapshot: Decimal  # stored balance snapshot after this event
    label: str  # human-readable for diagnostics


########################################################################
########################################################################
#
def _collect_events(budget: Budget) -> list[_Event]:
    """
    Return all balance-changing events for budget in service-layer order.

    Mirrors the ordering in transaction_allocation._recalculate_running_balances
    and recalculate_itx_snapshots_from_dt: InternalTransactions at timestamp T
    precede TransactionAllocations at T; within an event type, created_at (and
    tx.created_at for allocations) breaks ties.
    """
    events: list[_Event] = []

    allocs = (
        TransactionAllocation.objects.filter(budget=budget)
        .select_related("transaction")
        .order_by(
            "transaction__transaction_date",
            "transaction__created_at",
            "created_at",
        )
    )
    for alloc in allocs:
        tx = alloc.transaction
        events.append(
            _Event(
                sort_key=(
                    tx.transaction_date,
                    1,  # allocations come after ITxs at the same timestamp
                    tx.created_at,
                    alloc.created_at,
                ),
                delta=alloc.amount.amount,
                snapshot=alloc.budget_balance.amount,
                label=(
                    f"alloc  {str(alloc.id)[:8]}"
                    f"  tx={str(tx.id)[:8]}"
                    f"  {tx.transaction_date.date()}"
                    f"  amount={alloc.amount.amount:+.2f}"
                ),
            )
        )

    for itx in InternalTransaction.objects.filter(src_budget=budget).order_by(
        "effective_date", "created_at"
    ):
        events.append(
            _Event(
                sort_key=(
                    itx.effective_date,
                    0,  # ITxs come before allocations at the same timestamp
                    itx.created_at,
                    itx.created_at,
                ),
                delta=-itx.amount.amount,
                snapshot=itx.src_budget_balance.amount,
                label=(
                    f"itx    {str(itx.id)[:8]}"
                    f"  src-debit"
                    f"  {itx.effective_date.date()}"
                    f"  amount={-itx.amount.amount:+.2f}"
                ),
            )
        )

    for itx in InternalTransaction.objects.filter(dst_budget=budget).order_by(
        "effective_date", "created_at"
    ):
        events.append(
            _Event(
                sort_key=(
                    itx.effective_date,
                    0,
                    itx.created_at,
                    itx.created_at,
                ),
                delta=itx.amount.amount,
                snapshot=itx.dst_budget_balance.amount,
                label=(
                    f"itx    {str(itx.id)[:8]}"
                    f"  dst-credit"
                    f"  {itx.effective_date.date()}"
                    f"  amount={itx.amount.amount:+.2f}"
                ),
            )
        )

    events.sort(key=lambda e: e.sort_key)
    return events


########################################################################
########################################################################
#
def _check_budget_chain(
    budget: Budget,
    tolerance: Decimal,
) -> list[str]:
    """
    Walk the running-balance chain for budget and return error strings.

    Derives the initial balance (before all recorded events) from the
    current budget.balance using the same formula as the service layer, so
    a budget with no events at all always passes.

    Advances running using the stored snapshot rather than the expected value
    so that a single wrong snapshot does not cascade and obscure subsequent
    errors -- though a uniform offset across all snapshots will only surface
    at the first event and at the final-balance check.

    Returns an empty list when all chain invariants hold.
    """
    events = _collect_events(budget)
    if not events:
        return []

    errors: list[str] = []

    # Derive the initial balance before all events, matching the formula in
    # transaction_allocation._recalculate_running_balances.
    total_allocs = Decimal(
        TransactionAllocation.objects.filter(budget=budget).aggregate(
            total=Sum("amount")
        )["total"]
        or 0
    )
    total_credits = Decimal(
        InternalTransaction.objects.filter(dst_budget=budget).aggregate(
            total=Sum("amount")
        )["total"]
        or 0
    )
    total_debits = Decimal(
        InternalTransaction.objects.filter(src_budget=budget).aggregate(
            total=Sum("amount")
        )["total"]
        or 0
    )
    running = (
        budget.balance.amount - total_allocs - total_credits + total_debits
    )

    for event in events:
        expected = (running + event.delta).quantize(Decimal("0.01"))
        stored = event.snapshot.quantize(Decimal("0.01"))
        if abs(expected - stored) > tolerance:
            errors.append(
                f"    {event.label}"
                f"  expected={expected}"
                f"  stored={stored}"
                f"  off_by={stored - expected:+.2f}"
            )
        # Advance with stored snapshot to isolate individual errors rather
        # than cascading a single bad entry across the entire chain.
        running = event.snapshot

    # The last stored snapshot must equal the current budget.balance.
    final_stored = events[-1].snapshot.quantize(Decimal("0.01"))
    final_actual = budget.balance.amount.quantize(Decimal("0.01"))
    if abs(final_stored - final_actual) > tolerance:
        errors.append(
            f"    final snapshot={final_stored}"
            f"  budget.balance={final_actual}"
            f"  off_by={final_actual - final_stored:+.2f}"
        )

    return errors


########################################################################
########################################################################
#
class Command(BaseCommand):
    help = (
        "Verify sum(budget.balance)==available_balance, allocation sums, and "
        "budget running-balance chains for every BankAccount. "
        "Exits non-zero on any failure."
    )

    ####################################################################
    #
    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--account",
            metavar="PATTERN",
            help=(
                "Only check this BankAccount. Accepts a full UUID, "
                "UUID prefix/substring, or account name fragment "
                "(case-insensitive). Must resolve to exactly one account."
            ),
        )
        parser.add_argument(
            "--tolerance",
            type=Decimal,
            default=Decimal("0.00"),
            help=(
                "Absolute difference below which a value is still "
                "considered balanced. Default: 0.00 (exact match)."
            ),
        )

    ####################################################################
    #
    def handle(self, *args: Any, **options: Any) -> None:
        pattern: str | None = options["account"]
        tolerance: Decimal = options["tolerance"]

        if pattern:
            account = resolve_account(pattern)
            qs = BankAccount.objects.filter(pk=account.pk).order_by("name")
        else:
            qs = BankAccount.objects.all().order_by("name")

        total_accounts = 0
        account_failures: list[
            tuple[BankAccount, Decimal, Decimal, Decimal]
        ] = []
        posted_failures: list[
            tuple[BankAccount, Decimal, Decimal, Decimal]
        ] = []
        tx_failures: list[tuple[Transaction, Decimal, Decimal]] = []
        chain_failures: list[tuple[Budget, list[str]]] = []
        goal_failures: list[tuple[Budget, str]] = []

        for account in qs:
            total_accounts += 1

            # ----------------------------------------------------------
            # Level 1a: sum(budget.balance) == available_balance
            # Level 1b: posted_balance == budget_sum - sum(pending amounts)
            #
            # available_balance and budget balances both reflect pending
            # transactions (pending debits reduce available_balance and
            # are allocated to budgets, reducing budget balances).
            # posted_balance excludes pending transactions, so:
            #   posted_balance == budget_sum - pending_debit_sum
            # ----------------------------------------------------------
            budget_sum: Decimal = Budget.objects.filter(
                bank_account=account
            ).aggregate(total=Sum("balance"))["total"] or Decimal("0.00")

            available: Decimal = account.available_balance.amount.quantize(
                Decimal("0.01")
            )
            avail_delta = (available - budget_sum).quantize(Decimal("0.01"))

            pending_sum: Decimal = Decimal(
                Transaction.objects.filter(
                    bank_account=account, pending=True
                ).aggregate(total=Sum("amount"))["total"]
                or 0
            ).quantize(Decimal("0.01"))
            posted: Decimal = account.posted_balance.amount.quantize(
                Decimal("0.01")
            )
            expected_posted = (budget_sum - pending_sum).quantize(
                Decimal("0.01")
            )
            posted_delta = (posted - expected_posted).quantize(Decimal("0.01"))

            avail_ok = abs(avail_delta) <= tolerance
            posted_ok = abs(posted_delta) <= tolerance

            if avail_ok and posted_ok:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"PASS  {account.name} ({str(account.id)[:8]}): "
                        f"available={available}  budgets={budget_sum}"
                        f"  posted={posted}  pending={pending_sum}"
                    )
                )
            else:
                if not avail_ok:
                    account_failures.append(
                        (account, available, budget_sum, avail_delta)
                    )
                    self.stdout.write(
                        self.style.ERROR(
                            f"FAIL  {account.name} ({str(account.id)[:8]}): "
                            f"available={available}  budgets={budget_sum}"
                            f"  delta={avail_delta}"
                        )
                    )
                if not posted_ok:
                    posted_failures.append(
                        (account, posted, expected_posted, posted_delta)
                    )
                    self.stdout.write(
                        self.style.ERROR(
                            f"FAIL  {account.name} ({str(account.id)[:8]}): "
                            f"posted={posted}  expected={expected_posted}"
                            f"  delta={posted_delta}"
                            f"  (pending={pending_sum})"
                        )
                    )

            # ----------------------------------------------------------
            # Level 2: sum(allocation.amount) == transaction.amount
            # ----------------------------------------------------------
            txs = (
                Transaction.objects.filter(bank_account=account)
                .prefetch_related("allocations")
                .order_by("transaction_date", "created_at")
            )
            for tx in txs:
                alloc_sum = sum(
                    (a.amount.amount for a in tx.allocations.all()),
                    Decimal("0"),
                ).quantize(Decimal("0.01"))
                tx_amount = tx.amount.amount.quantize(Decimal("0.01"))
                if abs(tx_amount - alloc_sum) > tolerance:
                    tx_failures.append((tx, tx_amount, alloc_sum))
                    self.stdout.write(
                        self.style.ERROR(
                            f"FAIL  tx {str(tx.id)[:8]}"
                            f"  {tx.transaction_date.date()}"
                            f"  {tx.description[:40]!r}:"
                            f"  tx.amount={tx_amount}"
                            f"  alloc_sum={alloc_sum}"
                            f"  delta={tx_amount - alloc_sum:+.2f}"
                        )
                    )

            # ----------------------------------------------------------
            # Level 3: budget running-balance chains
            # ----------------------------------------------------------
            for budget in Budget.objects.filter(bank_account=account).order_by(
                "name"
            ):
                chain_errors = _check_budget_chain(budget, tolerance)
                if chain_errors:
                    chain_failures.append((budget, chain_errors))
                    archived_tag = " [archived]" if budget.archived else ""
                    self.stdout.write(
                        self.style.ERROR(
                            f"FAIL  budget {budget.name}{archived_tag}"
                            f" ({str(budget.id)[:8]})"
                            f" balance={budget.balance.amount}:"
                        )
                    )
                    for line in chain_errors:
                        self.stdout.write(self.style.ERROR(line))

            # ----------------------------------------------------------
            # Level 4: Goal funded_amount invariant
            #   balance == funded_amount + spent_amount
            # Unallocated is budget_type=GOAL (the model default) but is
            # seeded with account.available_balance -- a non-zero initial
            # balance that is never tracked in funded_amount.  The invariant
            # only applies to user-created Goals that start at zero.
            # ----------------------------------------------------------
            goal_qs = Budget.objects.filter(
                bank_account=account,
                budget_type=Budget.BudgetType.GOAL,
            )
            if account.unallocated_budget_id is not None:
                goal_qs = goal_qs.exclude(id=account.unallocated_budget_id)
            for budget in goal_qs.order_by("name"):
                error = _check_goal_invariant(budget, tolerance)
                if error is not None:
                    goal_failures.append((budget, error))
                    archived_tag = " [archived]" if budget.archived else ""
                    self.stdout.write(
                        self.style.ERROR(
                            f"FAIL  goal {budget.name}{archived_tag}"
                            f" ({str(budget.id)[:8]}):"
                        )
                    )
                    self.stdout.write(self.style.ERROR(error))

        # ------------------------------------------------------------------
        # Summary
        # ------------------------------------------------------------------
        self.stdout.write("")
        self.stdout.write(
            f"Checked {total_accounts} account(s):"
            f"  {len(account_failures)} available-balance failure(s),"
            f"  {len(posted_failures)} posted-balance failure(s),"
            f"  {len(tx_failures)} transaction failure(s),"
            f"  {len(chain_failures)} budget-chain failure(s),"
            f"  {len(goal_failures)} goal-invariant failure(s)."
        )

        any_failures = (
            account_failures
            or posted_failures
            or tx_failures
            or chain_failures
            or goal_failures
        )

        if account_failures:
            self.stdout.write("")
            self.stdout.write(
                "Per-budget breakdown for available-balance failures:"
            )
            for account, available, budget_sum, delta in account_failures:
                self.stdout.write("")
                self.stdout.write(
                    f"  {account.name} ({str(account.id)[:8]})"
                    f"  available={available}  budgets={budget_sum}"
                    f"  delta={delta}"
                )
                for budget in Budget.objects.filter(
                    bank_account=account
                ).order_by("name"):
                    archived_tag = " [archived]" if budget.archived else ""
                    self.stdout.write(
                        f"    {budget.balance.amount:>12}"
                        f"  {budget.name}{archived_tag}"
                    )

        if any_failures:
            raise CommandError(
                f"{len(account_failures)} available-balance, "
                f"{len(posted_failures)} posted-balance, "
                f"{len(tx_failures)} transaction, "
                f"{len(chain_failures)} budget-chain, "
                f"{len(goal_failures)} goal-invariant failure(s) found."
            )
