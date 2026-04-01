# mibudge

Personal budgeting service inspired by [Simple Bank](https://en.wikipedia.org/wiki/Simple_(bank)).

## What is this?

Simple Bank had a budgeting model that let you divide your checking account balance into virtual sub-accounts called "goals" and "expenses." When Simple shut down, nothing else replicated that experience well. mibudge is an attempt to rebuild and improve on that model for personal and family use.

### The core idea

You have one or more bank accounts. Each account's balance is divided into **budgets** and **goals** — virtual sub-accounts that live entirely inside mibudge. Every dollar in the account is allocated to one of these, with an "Unallocated" budget catching anything not yet assigned.

**Transactions** from the bank (purchases, deposits, transfers) are associated with a budget. Transactions may arrive as *pending* — recorded but not yet settled, with the final amount potentially differing from the pending amount (e.g. a gas station pre-authorization vs. the actual charge). A transaction represents one concrete bank event regardless of whether it is pending or posted. Most map to a single budget, but a transaction can be split — say, a store receipt that's part groceries and part home improvement supplies.

As money comes in (paychecks, etc.), it's automatically distributed to budgets and goals on a schedule, so that by the time a bill is due or a savings target arrives, the money is there.

### Budgets vs Goals

A **goal** has a target amount and a target date. Money accumulates on a funding schedule until the goal is reached. Once funded, it's complete.

A **budget** (recurring) is never truly complete. It has a refresh cycle — monthly, quarterly, yearly, etc. Money builds up until the target is reached, then resets on the next cycle. Think rent, groceries, subscriptions.

Recurring budgets can optionally have an associated **fill-up goal**. The fill-up goal is where automatic funding deposits go — not directly into the budget itself. Then, at the boundary between one refresh cycle and the next:

1. Money in the fill-up goal is transferred into the budget, up to the budget's target amount.
2. Any excess that doesn't fit (because the budget wasn't fully spent) stays in the fill-up goal.

For example: you have a monthly grocery budget with a $500 target. Throughout the month, automatic funding deposits accumulate in the fill-up goal. At the start of the cycle, the fill-up goal transfers $500 into the budget. You spend $400 that month. When the cycle refreshes, the $100 left in the budget doesn't need to move — the fill-up goal only needs to top the budget up to $500, so it contributes $400 instead of $500. That means the fill-up goal starts its next accumulation cycle with a $100 head start, needing only $400 in new funding to be ready for the following refresh. This also means you can have a fully funded budget that is ready to spend *while simultaneously* accumulating funds in the fill-up goal for the next cycle.

Both types can be funded automatically (calculated from schedule + target) or with a fixed amount per funding event.

### Accounts

mibudge supports multiple bank accounts — checking, savings, credit cards — each with their own set of budgets. Accounts can be shared between users (family members) or private to one user.

## Tech stack

- **Python 3.13+** / **Django 6.x** / **Django REST Framework**
- **Celery** + **Redis** for async task scheduling (budget funding, etc.)
- **PostgreSQL**
- **uv** for dependency management
- **ruff** for linting and formatting

## Development

Prerequisites: [uv](https://docs.astral.sh/uv/), Python 3.13+

```bash
# Install dependencies and create virtualenv
uv sync

# Run linter
make lint

# Run tests
uv run pytest

# Type checking
uv run mypy mibudge/ config/
```

## License

BSD
