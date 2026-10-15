# Bank activity simulator

`simulate_bank_activity` gives a development instance of mibudge realistic
bank data without anyone's real bank accounts, and lets you move a simulated
clock forward to watch budgets fill, reset and get overspent as time passes.

It acts as a fake bank. A **scenario file** describes a financial life --
banks and bank accounts, paychecks, bills, transfers, everyday spending --
and a **clock**, the simulated today. The simulator plays that life forward
and hands each simulated bank account's transactions to the same scrape-sync
service the live bank importer uses. mibudge then sees what it sees from a
real import:

- card purchases that are pending for a day or two and then post (a
  restaurant tip makes the posted amount larger than the authorization);
- paychecks split across bank accounts, rent and utilities by ACH, phone,
  internet and streaming charged to cards;
- refunds, ATM withdrawals and Zelle payments;
- transfers within a bank and between banks, credit card statements paid in
  full, savings interest at month end;
- merchant details (name, city, MCC) and categories on posted transactions;
- transfers and card payments linked across bank accounts.

The simulator creates no budgets or allocations; those are yours to make.

## Contents

- [Requirements](#requirements)
  - [The owner](#the-owner)
- [Quick start](#quick-start)
- [How it works](#how-it-works)
- [Walkthroughs](#walkthroughs)
- [Command reference](#command-reference)
- [Scenario file reference](#scenario-file-reference)
- [Things to avoid during a simulation](#things-to-avoid-during-a-simulation)
- [Troubleshooting](#troubleshooting)

## Requirements

- The database and Redis must be up (the simulator takes the same balance
  locks as every other writer). The web service, Celery worker and Celery
  beat do not need to run.
- The owner of the simulated bank accounts must be an existing user; the
  simulator never creates users. See [The owner](#the-owner).
- `init` uses [Faker](https://faker.readthedocs.io/) to make up names. Faker
  is a dev dependency, so `init` runs locally and in the dev image. The other
  verbs need only the scenario file.

All commands below run from the repository root:

```bash
uv run python app/manage.py simulate_bank_activity <verb> ...
```

### The owner

On a local dev stack, `make createadmin` creates a superuser to own the
simulated bank accounts and to sign in with:

```bash
make createadmin      # admin@example.com / testpass1234
```

To use your own address and password instead, create the user
interactively; it prompts for a username, email and password:

```bash
uv run python app/manage.py createsuperuser
```

Run either once; a second run fails because the user exists. Sign in to the
SPA at `/app/login/` with the email and password. Superuser status does not
bypass bank account ownership: the user sees only the bank accounts they own.

## Quick start

A starting data set: three months of history up to today.

```bash
make createadmin
uv run python app/manage.py simulate_bank_activity init sim.yaml --owner admin@example.com
uv run python app/manage.py simulate_bank_activity fill sim.yaml
```

Sign in at `/app/login/` as `admin@example.com` / `testpass1234`, and the SPA
shows six bank accounts at three banks, with three months of transactions, a
few of them still pending.

## How it works

**The scenario file is the simulation.** Every transaction is a pure function
of the scenario and the date: the same scenario always produces the same
transactions on the same day. The simulator keeps no other state, so there is
nothing to get out of step: after editing the scenario, `reset` and `fill`
replay the history up to the current clock.

**The clock is the simulated today.** `fill` simulates from `start` to
`clock`. `advance` moves the clock forward one day at a time. For each day it
sends that day's bank snapshot (new posted transactions, the current pending
ones) to mibudge, and then runs budget funding *for that day*. `clock:` is the
only line of the scenario file the simulator writes; it rewrites it after each
day, leaving your edits and comments alone. The clock never passes the real
date.

**Funding follows the simulated clock.** Scheduled funding is switched off for
the simulated bank accounts (`auto_funding_enabled`). `advance` funds them
itself, with the simulated date, right after each day's transactions arrive.
Budgets therefore fill and reset on the simulated timeline whether or not
Celery is running. Spending that lands before a budget's funding day shows up
as spending before the budget is funded, exactly as it would in real life.

**Business days follow the Federal Reserve calendar.** Weekends and the Fed
holidays move paydays to the business day before, and ACH debits, transfers
and card settlement to the business day after. A holiday on a Sunday is
observed the Monday after; one on a Saturday is not moved.

**Linking.** Transfers and card payments within one bank name the other bank
account's last four digits ("... ENDING IN 4821"). A card at another bank is
paid with the issuer's e-payment description, which names no account number;
mibudge links that through the card's `link_aliases`. A transfer between banks
arrives a day or more after it leaves, and mibudge links the two sides when
they are at most three days apart, so one that straddles a weekend and a
holiday stays unlinked -- as it would with real data.

## Walkthroughs

The dates below are examples; pick dates before today.

### 1. A starting data set for development

```bash
uv run python app/manage.py simulate_bank_activity init sim.yaml \
    --owner admin@example.com --start 2026-04-01
uv run python app/manage.py simulate_bank_activity fill sim.yaml
```

`--through` (the initial clock) defaults to today. `fill` prints what it
inserted for each bank account and how many of the new transactions are
linked to their counterparts.

To bring the data up to date later, advance to today:

```bash
uv run python app/manage.py simulate_bank_activity advance sim.yaml --to 2026-10-15
```

### 2. Watching budgets fill as time passes

Start the clock in the past, so there is room to move it forward:

```bash
uv run python app/manage.py simulate_bank_activity init sim.yaml \
    --owner admin@example.com --start 2026-06-01 --through 2026-08-10
uv run python app/manage.py simulate_bank_activity fill sim.yaml
```

Create budgets with `define_budgets`, giving each funding schedule a `DTSTART`
on the **first funding day after the clock**. Without a `DTSTART`, mibudge
anchors a new budget's schedule on the real date, so it would not fund until
the simulated clock caught up with today.

```yaml
# budgets.yaml
bank_account: "Everyday Checking"
budgets:
  - name: Vacation
    type: goal
    funding_type: fixed_amount
    target_balance: "1200.00"
    funding_amount: "100.00"
    funding_schedule: |
      DTSTART:20260815T000000Z
      RRULE:FREQ=MONTHLY;BYMONTHDAY=15,-1
```

For a recurring budget, give the `recurrence_schedule` a `DTSTART` too.

```bash
uv run python app/manage.py define_budgets budgets.yaml
```

Now step through time and watch the budget in the SPA after each step:

```bash
uv run python app/manage.py simulate_bank_activity advance sim.yaml 1d
uv run python app/manage.py simulate_bank_activity advance sim.yaml --to 15
uv run python app/manage.py simulate_bank_activity advance sim.yaml 2w
```

Each simulated day prints one line, for example:

```
2026-08-14 Fri: 5 posted, 3 pending, 0 funding transfers
2026-08-15 Sat: 1 posted, 5 pending, 1 funding transfer
```

### 3. Spending before a budget is funded

Pick a budget funded mid-month and spending that lands early in the month.
For example, raise the scenario's grocery spending and fund a groceries
budget on the 15th:

```yaml
spending:
  - name: groceries
    category: "Food & Drink : Groceries"
    per_week: 4.0              # was 2.0
    amount: ["60.00", "220.00"]
```

Editing the scenario changes its history, so start over:

```bash
uv run python app/manage.py simulate_bank_activity reset sim.yaml
uv run python app/manage.py simulate_bank_activity fill sim.yaml
```

Then define the budget, assign the early-month grocery purchases to it in the
SPA, and advance past the 15th to see the budget go negative and then catch up
when it is funded.

### 4. A payday before a weekend or holiday

Set the clock just before a payday that falls on a weekend or holiday and
advance across it. In August 2026 the 15th is a Saturday, so pay arrives on
Friday the 14th, a day before a budget funded on the 15th:

```bash
uv run python app/manage.py simulate_bank_activity init sim.yaml \
    --owner admin@example.com --start 2026-06-01 --through 2026-08-12
uv run python app/manage.py simulate_bank_activity fill sim.yaml
uv run python app/manage.py simulate_bank_activity advance sim.yaml --to 17
```

Labor Day works the same way for ACH debits: a bill due Saturday
2026-09-05 posts on Tuesday the 8th.

### 5. Transfers and card payments across bank accounts

The generated scenario covers every linking path:

| What | Where to look |
|------|---------------|
| Transfer within one bank | Everyday Checking -> Savings, on the 1st |
| Transfer between banks | Everyday Checking -> High-Yield Savings, on the 2nd; arrives a day later |
| Card payment within one bank | Everyday Checking -> Rewards Card, on the 15th |
| Card payment to another bank | Everyday Checking -> Travel Card, on the 28th; linked through `link_aliases` |

Each pair shows up in the SPA as linked transactions.

### 6. More than one simulation

Each scenario needs its own bank names and account numbers. `init` with a
different `--seed` makes up different names and numbers. The owner can be
the same user or another existing one (create a second with
`manage.py createsuperuser`):

```bash
uv run python app/manage.py simulate_bank_activity init second.yaml \
    --owner partner@example.com --seed 2
```

## Command reference

| Verb | What it does |
|------|--------------|
| `init FILE --owner EMAIL [--start DATE] [--through DATE] [--seed N]` | Write a new scenario file. `--through`, the initial clock, defaults to today; `--start` to 90 days before it. Refuses to overwrite a file. |
| `fill FILE` | Create the scenario's banks and bank accounts and simulate from `start` to `clock`. Sends no notifications. Refuses if the bank accounts already exist. |
| `advance FILE STEP` | Move the clock forward `Nd` days or `Nw` weeks (`1d`, `3d`, `2w`). |
| `advance FILE --to DAY` | Move the clock to the next given day of the month (`--to 15`; past a short month's end means its last day). |
| `advance FILE --to DATE` | Move the clock to a date (`--to 2026-09-01`). |
| `reset FILE` | Delete the scenario's bank accounts, and their banks once empty. |

`advance` syncs and funds each simulated day in turn and writes the clock
after each one, so an interrupted run leaves the clock on the last day it
finished. Notifications come from the last day only.

The simulator only ever touches bank accounts that belong to the scenario's
banks, carry its bank account names and are owned by its owner. If a bank
account with one of those names belongs to someone else, it refuses to run.

## Scenario file reference

`init` writes a complete, commented scenario; this is the reference for
editing one. Amounts are strings in the bank account's currency, and an
amount written `[min, max]` picks a value in that range, weighted towards the
low end. Categories are mibudge category full names (`"Group : Name"`). A day
of the month past a short month's end means its last day.

### Top level

| Key | Meaning |
|-----|---------|
| `seed` | Random seed; change it for a different but equally plausible history. |
| `owner` | Email of the existing user who owns the bank accounts. |
| `start` | The first simulated day. |
| `clock` | The simulated today. Keep it a single `clock: YYYY-MM-DD` line. |

### `banks`

A list of banks, each with a `name` and its `accounts`:

| Key | Meaning |
|-----|---------|
| `key` | How the rest of the file refers to this bank account. |
| `name` | What mibudge shows. |
| `type` | `checking`, `savings` or `credit_card`. |
| `account_number` | Unique across the database; its last four digits link transfers. |
| `opening_balance` | Deposited on `start` (not on credit cards). |
| `interest_apy` | Annual percentage yield, credited on the last day of each month. |
| `link_aliases` | Text that identifies this bank account in another bank account's descriptions. |
| `statement_day` | Credit cards: the day the statement closes. |
| `payment_day` | Credit cards: the day the statement balance is paid in full. |
| `pay_from` | Credit cards: the bank account that pays it. |

### `paychecks`

| Key | Meaning |
|-----|---------|
| `employer` | Appears in the payroll description. |
| `schedule` | `semimonthly` (the 15th and the last day) or `biweekly`. |
| `anchor` | `biweekly` only: a payday; pay repeats every 14 days from it. |
| `net_amount` | The whole paycheck. |
| `deposits` | How it is split: each entry names an `account` and an `amount`, except one with `remainder: true`, which gets the rest. |

### `transfers`

Monthly moves between your own bank accounts: `from`, `to`, `amount`, `day`,
and for a transfer between banks `lag_days: [min, max]`, how many days later
it arrives (0 to 5, then rolled to a business day).

### `bills`

| Key | Meaning |
|-----|---------|
| `payee` | Appears in the description. |
| `amount`, `day` | How much, on which day of the month. |
| `account` | The bank account that pays. |
| `method` | `ach` (posts that day, rolled to a business day) or `card` (a card charge: pending, then posted). |
| `category` | Category of the posted transaction. |
| `city`, `state`, `mcc` | `card` bills: the merchant details. |

### `spending`

| Key | Meaning |
|-----|---------|
| `name` | A label, unique in the file. |
| `kind` | `purchase` (default), `atm` (cash, posts at once) or `zelle` (pays a person, posts at once). |
| `per_week` | How often, on average. |
| `weekdays` | Weights spreading it over the week, e.g. `{fri: 1, sat: 2, sun: 1}`; unnamed days get none. Default: every day, a little busier at the weekend. |
| `amount` | How much. |
| `round_to` | Round amounts to a multiple of this (ATM cash). |
| `accounts` | Weights choosing the bank account, e.g. `{card: 3, checking: 1}`. |
| `merchants` | Where: each has a `name`, and optionally `city`, `state`, `mcc`. |
| `category` | Category of the posted transactions. |
| `settle_days` | `[min, max]` days a purchase stays pending (0 to 4, then rolled to a business day). |
| `tip` | `[min, max]` fraction the posted amount exceeds the authorization by. |
| `refund_rate` | Chance a purchase is refunded a few days later. |

## Things to avoid during a simulation

The simulated clock is behind the real date. Three things in the SPA work on
the real date and so break a simulation.

**"Run funding now".** The simulator funds the simulated bank accounts itself,
one simulated day at a time. "Run funding now" ignores the scheduled-funding
switch and funds through *today's real date*. On a simulated bank account it
processes every funding and recurrence event between the simulator's clock and
today in one go: budgets fill weeks early, recurring budgets reset ahead of
schedule, and the money moves against balances that don't yet include the
spending the simulator would generate for those days. Advancing the simulator
afterwards doesn't undo it: those events are already recorded as done, so the
simulator skips them. To recover, `reset` and `fill`.

**Unpausing a budget.** Its funding resumes from the real yesterday, so the
simulated days in between are skipped.

**Creating or editing a budget.** Its funding schedule is anchored on the real
date, so it doesn't fund until the simulated clock catches up. Create and
change budgets with `define_budgets` and a `DTSTART`, as in
[walkthrough 2](#2-watching-budgets-fill-as-time-passes).

## Troubleshooting

| Message | Meaning |
|---------|---------|
| `No user has the email ...` | Create the owner first (see [The owner](#the-owner)); the simulator never creates users. |
| `... already exists; use 'advance', or 'reset' first` | The scenario was already filled. |
| `... does not exist; run 'fill' first` | `advance` needs filled bank accounts. |
| `... is later than today` | The clock cannot pass the real date. |
| `... account number ... is already in use` | Another scenario (or a real bank account) uses that number; change it, or `init` with another `--seed`. |
| `... exists but is not owned by ...` | A bank account with a scenario name belongs to someone else; rename the bank or bank account in the scenario. |
| `balance differs from the simulation by ...` | The simulated bank accounts no longer match the scenario: it was edited without `reset`, or their transactions were changed outside the simulator. `reset` and `fill`. |
| `unknown category ...` | A scenario category is not a mibudge category full name; its transactions stay unassigned. |
