# Generated data migration — elidable.
#
"""
Recalculate budget_balance (running balance) snapshots on all
TransactionAllocation rows.

Prior to the signal fix, allocations recorded budget_balance in
creation order rather than chronological transaction order.  This
migration walks every budget's allocations in the correct order
(transaction_date, transaction.created_at, allocation.created_at)
and fixes the snapshots.

Elidable: fresh databases have no stale data, so this is a no-op
on new installs.
"""

from decimal import Decimal

from django.db import migrations
from django.db.models import Sum
from moneyed import Money

def fix_running_balances(apps, schema_editor):
    Budget = apps.get_model("moneypools", "Budget")
    TransactionAllocation = apps.get_model(
        "moneypools", "TransactionAllocation"
    )

    chronological = (
        "transaction__transaction_date",
        "transaction__created_at",
        "created_at",
    )

    for budget in Budget.objects.iterator():
        allocs = (
            TransactionAllocation.objects.filter(budget=budget)
            .order_by(*chronological)
            .select_related("transaction")
        )

        total = allocs.aggregate(total=Sum("amount"))["total"] or Decimal(
            "0"
        )
        total_money = Money(total, currency=budget.balance.currency)
        running = budget.balance - total_money

        for alloc in allocs:
            running += alloc.amount
            if alloc.budget_balance != running:
                TransactionAllocation.objects.filter(pk=alloc.pk).update(
                    budget_balance=running
                )


class Migration(migrations.Migration):

    dependencies = [
        ("moneypools", "0018_alter_budget_fillup_goal"),
    ]

    operations = [
        migrations.RunPython(
            fix_running_balances,
            reverse_code=migrations.RunPython.noop,
            elidable=True,
        ),
    ]
