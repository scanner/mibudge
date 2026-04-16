# Data migration: create fill-up goal budgets for any existing Recurring
# budgets that have with_fillup_goal=True but no fillup_goal FK set.
#
# The budget_post_save signal now handles this automatically going forward,
# but budgets created before that signal was added are missing their
# associated type-A fill-up budget.
#
from django.db import migrations


def create_missing_fillup_budgets(apps, schema_editor):
    """Create type-A fill-up budgets for any Recurring budgets that lack one."""
    Budget = apps.get_model("moneypools", "Budget")

    orphans = Budget.objects.filter(
        budget_type="R",
        with_fillup_goal=True,
        fillup_goal__isnull=True,
    )
    for budget in orphans:
        fillup = Budget.objects.create(
            name=f"{budget.name} Fill-up",
            bank_account=budget.bank_account,
            budget_type="A",
            funding_schedule=budget.funding_schedule,
            target_balance=budget.target_balance,
            target_balance_currency=budget.target_balance_currency,
        )
        Budget.objects.filter(pk=budget.pk).update(fillup_goal=fillup)


def reverse_migration(apps, schema_editor):
    """Remove fill-up budgets that were created by the forward migration.

    Only removes type-A budgets whose parent still points at them and
    whose name follows the "<parent> Fill-up" convention, to avoid
    touching any manually-created fill-up budgets.
    """
    Budget = apps.get_model("moneypools", "Budget")

    for budget in Budget.objects.filter(budget_type="R", fillup_goal__isnull=False):
        fillup = budget.fillup_goal
        if fillup and fillup.name == f"{budget.name} Fill-up":
            Budget.objects.filter(pk=budget.pk).update(fillup_goal=None)
            fillup.delete()


class Migration(migrations.Migration):

    dependencies = [
        ("moneypools", "0016_budget_funding_amount_budget_funding_amount_currency"),
    ]

    operations = [
        migrations.RunPython(
            create_missing_fillup_budgets,
            reverse_code=reverse_migration,
            elidable=True,
        ),
    ]
