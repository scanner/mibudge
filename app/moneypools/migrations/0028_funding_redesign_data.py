"""
Data migration for funding redesign (Task A).

Steps:
  1. Guard: error out if any Capped budget has TARGET_DATE funding or a
     non-null target_date -- those must be fixed manually before this
     migration can run.
  2. Backfill Budget.funded_amount for Goal budgets: net of all ITX
     credits minus debits (all InternalTransactions, not just system ones).
  3. Backfill system_event_kind and system_event_date on ITXs issued by
     the funding-system user.  Kind is inferred from src/dst topology:
       - src == Unallocated  -> "F" (fund event)
       - dst is Recurring and src == dst.fillup_goal  -> "R" (recur event)
       - ambiguous -> left null; row is logged for operator review.
     system_event_date is set to effective_date.date() if effective_date is
     set, else created_at.date().
  4. Auto-create an Associated Fill-up sibling for every Recurring budget
     that lacks a fillup_goal (legacy with_fillup_goal=False rows).
"""

import logging

from django.db import migrations, models

logger = logging.getLogger(__name__)


####################################################################
#
def _forward(apps, schema_editor):
    Budget = apps.get_model("moneypools", "Budget")
    InternalTransaction = apps.get_model("moneypools", "InternalTransaction")
    User = apps.get_model("users", "User")

    # ------------------------------------------------------------------
    # Step 1: guard against bad Capped data
    # ------------------------------------------------------------------
    bad_capped = list(
        Budget.objects.filter(budget_type="C").filter(
            models.Q(funding_type="D") | models.Q(target_date__isnull=False)
        )
    )
    if bad_capped:
        ids = ", ".join(str(b.id) for b in bad_capped)
        raise Exception(
            f"Migration aborted: the following Capped budget(s) have "
            f"TARGET_DATE funding or a non-null target_date and must be "
            f"fixed manually before re-running this migration: {ids}"
        )

    # ------------------------------------------------------------------
    # Step 2: backfill funded_amount for Goal budgets
    # ------------------------------------------------------------------
    goal_budgets = Budget.objects.filter(budget_type="G")
    for budget in goal_budgets:
        credits = (
            InternalTransaction.objects.filter(dst_budget=budget).aggregate(
                total=models.Sum("amount")
            )["total"]
            or 0
        )
        debits = (
            InternalTransaction.objects.filter(src_budget=budget).aggregate(
                total=models.Sum("amount")
            )["total"]
            or 0
        )
        net = credits - debits
        Budget.objects.filter(pk=budget.pk).update(funded_amount=net)

    # ------------------------------------------------------------------
    # Step 3: backfill system_event_kind / system_event_date
    # ------------------------------------------------------------------
    try:
        system_user = User.objects.get(username="funding-system")
    except User.DoesNotExist:
        logger.warning(
            "funding-system user not found; skipping ITX backfill"
        )
        system_user = None

    if system_user is not None:
        # Build a lookup: budget_id -> unallocated budget_id for each account
        unallocated_ids = set(
            Budget.objects.filter(
                bank_account__unallocated_budget__isnull=False
            ).values_list(
                "bank_account__unallocated_budget_id", flat=True
            )
        )
        # Build a lookup: fillup_goal_id -> parent recurring budget
        fillup_to_parent = {
            b.fillup_goal_id: b
            for b in Budget.objects.filter(
                budget_type="R", fillup_goal__isnull=False
            ).select_related("fillup_goal")
        }

        ambiguous_count = 0
        for itx in InternalTransaction.objects.filter(
            actor=system_user
        ).select_related("src_budget", "dst_budget"):
            kind = None

            if itx.src_budget_id in unallocated_ids:
                kind = "F"
            elif (
                itx.dst_budget.budget_type == "R"
                and itx.src_budget_id == itx.dst_budget.fillup_goal_id
            ):
                kind = "R"
            else:
                ambiguous_count += 1
                logger.warning(
                    "ITX %s (src=%s dst=%s) actor=funding-system but "
                    "topology is ambiguous; leaving system_event_kind null",
                    itx.id,
                    itx.src_budget_id,
                    itx.dst_budget_id,
                )

            event_date = (
                itx.effective_date.date()
                if itx.effective_date
                else itx.created_at.date()
            )
            InternalTransaction.objects.filter(pk=itx.pk).update(
                system_event_kind=kind,
                system_event_date=event_date,
            )

        if ambiguous_count:
            logger.warning(
                "%d system ITX row(s) had ambiguous topology and were left "
                "with system_event_kind=null. Review them manually.",
                ambiguous_count,
            )

    # ------------------------------------------------------------------
    # Step 4: create fill-up siblings for legacy Recurring budgets
    # ------------------------------------------------------------------
    legacy_recurring = Budget.objects.filter(
        budget_type="R", fillup_goal__isnull=True
    )
    for budget in legacy_recurring:
        fillup = Budget(
            name=f"{budget.name} Fill-up",
            bank_account=budget.bank_account,
            budget_type="A",
            funding_schedule=budget.funding_schedule,
            funding_type=budget.funding_type,
            target_balance=budget.target_balance,
        )
        fillup.save()
        Budget.objects.filter(pk=budget.pk).update(fillup_goal_id=fillup.pk)
        logger.info(
            "Created fill-up sibling '%s' (pk=%s) for Recurring budget "
            "'%s' (pk=%s)",
            fillup.name,
            fillup.pk,
            budget.name,
            budget.pk,
        )


####################################################################
#
def _reverse(apps, schema_editor):
    # Funded-amount and ITX fields can be reset to defaults; fill-up
    # siblings created by this migration are deleted.
    Budget = apps.get_model("moneypools", "Budget")
    InternalTransaction = apps.get_model("moneypools", "InternalTransaction")

    Budget.objects.filter(budget_type="G").update(funded_amount=0)
    InternalTransaction.objects.update(
        system_event_kind=None, system_event_date=None
    )
    # We cannot reliably identify which fill-up siblings were created by
    # this migration vs pre-existing ones, so we leave them in place.


########################################################################
########################################################################
#
class Migration(migrations.Migration):
    dependencies = [
        ("moneypools", "0027_funding_redesign_schema"),
    ]

    operations = [
        migrations.RunPython(_forward, reverse_code=_reverse),
    ]
