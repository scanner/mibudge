# Funding — Implementation Reference

This document describes how the mibudge funding engine works as actually
implemented.  It is written for contributors who want to understand, work
on, or modify the funding system.  Every claim here is tied to a
specific file and function.

---

## 1. Overview

**Funding** moves money from an account's `Unallocated` budget into other
budgets on that account, on a schedule.  No real bank transfer happens —
funding is reallocation inside the virtual accounting layer.

The engine's entry point is `fund_account()` in
`app/moneypools/service/funding.py`.  It runs **idempotently** per bank
account: re-running it any number of times is safe because each
scheduled event has a `FundingEventOccurrence` row whose terminal status
(`COMPLETE` or `SKIPPED`) prevents double-processing.

Concurrency across workers is handled by a non-blocking Redis lock on
`account.lock_key`.  A second concurrent caller returns
`FundingReport(busy=True)` immediately rather than wait or duplicate
transfers.

The engine is invoked from three places:

| Caller                | Where                                                           | Frequency           |
|-----------------------|-----------------------------------------------------------------|---------------------|
| Celery Beat scheduler | `app/moneypools/tasks.py:schedule_funding_runs`                 | Every 30 minutes    |
| REST API              | `app/moneypools/api/v1/views.py:BankAccountViewSet.run_funding` | On user request     |
| Management command    | `app/moneypools/management/commands/fund_budgets.py`            | On operator request |

The three entry points differ in two ways: which event kinds they process
and whether they send notifications.  Details in §5.


---

## 2. Budget types

There are three user-facing budget types plus one supporting type:

| Type                   | Purpose                                                      | Fill-up?        | Funding types                 |
|------------------------|--------------------------------------------------------------|-----------------|-------------------------------|
| **Goal**               | One-shot accumulation toward a target                        | No              | `FIXED_AMOUNT`, `TARGET_DATE` |
| **Capped**             | Perpetually topped up to a cap                               | No              | `FIXED_AMOUNT` only           |
| **Recurring**          | Periodic budget that resets on a cycle                       | Yes (mandatory) | `TARGET_DATE` only            |
| **Associated Fill-up** | Sibling of a Recurring; accumulates funding across the cycle | n/a             | n/a                           |

A Recurring budget always has exactly one Associated Fill-up sibling,
created automatically at budget creation by
`app/moneypools/service/budget.py:_maybe_create_fillup()` and linked via
`Budget.fillup_goal`.  The fill-up has no schedule of its own; it is
funded and drained entirely through its parent Recurring's events.

The `Unallocated` budget on each account is auto-created per account and
is never funded by the engine.


---

## 3. Event model

The engine recognises two event kinds, defined as `EventKind` in
`app/moneypools/models.py`:

- **Fund event** — fires on `budget.funding_schedule`.  For Goal and
  Capped, the destination is the budget itself.  For Recurring, the
  destination is the fill-up sibling (not the Recurring budget directly).
- **Recur event** — fires on `budget.recurrence_schedule`.  Only
  Recurring budgets have these.  Source is the fill-up; destination is
  the Recurring budget.

When a fund event and a recur event fall on the same day for the same
Recurring budget, the **fund event runs first** within a single engine
call.  This guarantees the fill-up has its maximum available balance
before the recur sweep when both events are processed together (e.g. via
"Run funding now").

The sort key is `(date asc, FUND before RECUR, budget.id asc)`.
Implemented at `funding.py:FundingEvent.sort_key()`.

**Important for automatic scheduling:** the in-engine sort order only
applies when both events are processed in the same call.  Under the
automatic scheduler, FUND fires at 23:00 and RECUR fires at 03:00 in
separate windows.  If the fund date and recur date are the same calendar
day, RECUR runs at 03:00 (before any that day's funding) and FUND does
not fire until 23:00 that evening — the fill-up will be in its
pre-funding state when the sweep runs.  See §5.0 for the recommended
date layout.


### 3.1 FundingEventOccurrence

**File:** `app/moneypools/models.py:FundingEventOccurrence`

Each (budget, kind, scheduled_date) tuple that the engine enumerates
has a corresponding `FundingEventOccurrence` row.  The row is created on
the first run that touches that event and carries forward across re-runs.

```
PENDING  → COMPLETE (full intended amount transferred)
PENDING  → SKIPPED  (budget was paused, or a newer event superseded this one)
```

Terminal states (`COMPLETE`, `SKIPPED`) are never re-opened.  The
processing loop skips them immediately, making "Run funding now" safe to
click repeatedly.

**FUND vs. RECUR semantics differ:**

- **FUND** — always reaches COMPLETE on the first pass.  The full
  intended amount transfers regardless of the Unallocated balance;
  Unallocated may go negative (see §5.0 for the design rationale).
  No retry is needed.
- **RECUR** — is always COMPLETE after one pass, even when the fill-up
  lacked sufficient funds.  There is no retry: the cycle has ended and
  the next cycle starts fresh.

`FundingEventOccurrence.Status` is a `TextChoices` inner class with
values `PENDING`, `PARTIAL`, `COMPLETE`, `SKIPPED`.  The `PARTIAL`
status exists in the database schema but is not reached by the current
engine; all events complete on their first pass.

A unique constraint on `(budget, kind, scheduled_date)` prevents
duplicate rows for the same event.  A partial index on `(budget,
scheduled_date)` where `status IN ('PENDING', 'PARTIAL')` keeps the
"what's outstanding?" query cheap as COMPLETE rows accumulate.

`Budget.last_funded_on` and `Budget.last_recurrence_on` are
denormalized caches of the most recent COMPLETE occurrence date for
each kind.  They are kept by `_mark_occurrence_complete` so that
`_collect_events` and `next_funding_info` can use them without joining
the occurrence table.


---

## 4. Per-event amount formulas

Each budget type has a strategy class in
`app/moneypools/service/funding_strategy.py` that computes the intended
transfer amount for a single event.  All formulas operate on
**state at the start of the event date** — defined in §7.

The following notation is used:

| Symbol        | Meaning                                                          |
|---------------|------------------------------------------------------------------|
| `T`           | `budget.target_balance`                                          |
| `F_0`         | `budget.funded_amount` rolled back to start of event date        |
| `B_0`         | `budget.balance` rolled back to start of event date              |
| `Fill_B_0`    | `budget.fillup_goal.balance` rolled back to start of event date  |
| `A`           | `budget.funding_amount` (FIXED_AMOUNT budgets)                   |
| `N_to_target` | Schedule occurrences from event_date through target_date (min 1) |
| `N`           | Remaining funding events in the current recurrence cycle (min 1) |

### 4.1 Goal + FIXED_AMOUNT  (`GoalStrategy`)

```
intended = min(A, max(0, T - F_0))
```

Uses `funded_amount_0`, not `balance_0`.  Spending debits `balance` but
not `funded_amount`; treating spending as unfunded gap would over-fund.

### 4.2 Goal + TARGET_DATE  (`GoalStrategy`)

```
intended = max(0, T - F_0) / N_to_target
```

After `target_date` passes, `count_occurrences()` returns 1, so the full
remaining gap is closed in one event and a warning is emitted.

### 4.3 Capped (`CappedStrategy`)

```
intended = min(A, max(0, T - B_0))
```

Uses `balance_0` (not `funded_amount_0`).  Capped budgets never reach
`complete=True`.

### 4.4 Recurring — fund event (`RecurringStrategy._intended_fund`)

```
intended = (T - Fill_B_0) / N
```

where `N` is the count of remaining fund-schedule events from `event_date`
(inclusive) through the next recurrence boundary (inclusive).  Computed
by `_fill_amount_prorated()`.  The first-cycle case projects a theoretical
prior boundary backward to avoid inflating `N`.

Money flows to the **fill-up**, not to the Recurring budget.

### 4.5 Recurring — recur event (`RecurringStrategy._intended_recur`)

```
intended = max(0, T - B_0(Recurring))
```

The fill-up balance caps the actual transfer; the engine applies that
cap externally.


---

## 5. Entry points and call chains

### 5.0 Automatic vs. manual funding

Automatic funding (`auto_funding_enabled=True`) is designed for users
whose income is predictable: they know their pay schedule and typical
deposit amounts, and have set their budget funding amounts accordingly.
The engine transfers the full intended amount at 23:00 on each fund date
**without checking** whether Unallocated has sufficient funds.

A paycheck that is still pending at 23:00 on a fund date will cause
Unallocated to go temporarily negative.  This is expected and by design:
the system assumes the user has calibrated their funding amounts against
their real income, so the negative balance will self-correct when the
deposit posts.  The timing window between a fund event and the deposit
clearing is typically a few hours to a couple of days.

If a user's funding amounts exceed what actually lands in their account
over time, Unallocated will drift increasingly negative and will not
self-correct.  This is a signal that funding amounts are misconfigured
and need to be reduced to match actual income.

**Scheduling the fill-up correctly.**  For automatic funding to guarantee
the fill-up is fully funded before the recur sweep, the recur date must
fall the day after the last fund date in the cycle.  The canonical
pattern is to fund on the last day of the month and recur on the first
day of the next month: the fund event fills the fill-up at 23:00 on the
last day, and the recur event sweeps it into the recurring budget at
03:00 the following morning — approximately four hours later.

If the recur date and a fund date share the same calendar day, the recur
sweep runs at 03:00 (before any of that day's deposits or funding) and
the fill-up will be in its state from the previous funding cycle when the
sweep runs.  That is still correct behaviour: the fill-up was built up by
all the fund events in the completed cycle, and the same-day fund event
at 23:00 begins filling it for the next cycle.  For example, if a
recurring budget recurs on the 15th and is funded on both the 15th and
the last day of the month, the May 15th recur sweep draws on what was
accumulated through April 30th; the May 15th fund event at 23:00 then
starts filling the fill-up toward the June 15th recurrence.

Users whose income is irregular or unpredictable may be better served by
turning off automatic funding and using the **"Run funding now"** button
on the account page after each deposit posts.  This gives direct control
over timing: both FUND and RECUR events run immediately on demand,
within a single engine call where FUND always sorts before RECUR,
without waiting for the 23:00 or 03:00 scheduled windows.


### 5.1 Celery Beat scheduler

**File:** `app/moneypools/tasks.py`

`schedule_funding_runs` is registered in
`app/config/celery_app.py:MANAGED_PERIODIC_TASKS` with crontab
`{"minute": "0,30"}` — it fires every 30 minutes, all day.

Accounts with `auto_funding_enabled=False` are skipped by the scheduler.
The owner has opted out of automatic funding and will drive funding
manually via the "Run funding now" REST endpoint.

On each tick, for each remaining account it:

1. Reads the first owner's IANA timezone (`owner.timezone`).
2. Appends `(account_id, local_date_str)` to `fund_accounts`
   when local time is in `[23:00, 23:30)`.
3. Appends to `recur_accounts` only when local time is in
   `[03:00, 03:30)`.
4. Spreads tasks evenly across up to 30 minutes to avoid a DB stampede.

`fund_one_account` fires once per day in the `[23:00, 23:30)` local
window — in the evening on the fund date, consistent with typical
payroll deposit timing.  FUND events always transfer the full intended
amount regardless of the Unallocated balance, so no mid-day retry pass
is needed.

`recur_one_account` fires only in the `[03:00, 03:30)` local window.
RECUR is one-shot (always COMPLETE on first pass), so a single fire per
day is correct.  The ~4-hour gap between the 23:00 FUND window and the
03:00 RECUR window gives the fill-up goal time to be fully funded before
the sweep into the recurring budget.

Two Celery tasks are dispatched:

```
schedule_funding_runs
├── fund_one_account(account_id, local_date_str)     # 23:00–23:30 only
│     └── _run_funding_task(..., kinds={EventKind.FUND}, ...)
│           └── fund_account(account, today, actor, kinds={FUND})
│                 [returns FundingReport]
│           if report.busy: log and return
│           if report.funded_budgets:
│               notify_for(account, FUNDING_COMPLETE, {...})
│
└── recur_one_account(account_id, local_date_str)    # 03:00–03:30 only
      └── _run_funding_task(..., kinds={EventKind.RECUR}, ...)
            └── fund_account(account, today, actor, kinds={RECUR})
                  [returns FundingReport]
            if report.busy: log and return
            if report.funded_budgets:
                notify_for(account, FUNDING_COMPLETE, {...})
```

`_run_funding_task` handles account lookup, system-user lookup, and
`local_date_str` parsing before calling `fund_account`.

### 5.2 REST API endpoint (manual funding)

**File:** `app/moneypools/api/v1/views.py:BankAccountViewSet.run_funding`

`POST /api/v1/bank-accounts/<id>/run-funding/`

This endpoint backs the **"Run funding now"** button on the account page
in the SPA.  It processes both FUND and RECUR events (`kinds=None`) in a
single pass, so users with `auto_funding_enabled=False` can trigger a
complete funding cycle — fill the fill-up and sweep it into the recurring
budget — with one click after a deposit has posted.

`auto_funding_enabled` is **not** checked here — users can always trigger
funding manually regardless of the account's automation setting.  A user
with automatic funding enabled can also use this to process a catch-up
run outside the scheduled windows.

An optional `as_of` date in the request body lets the caller specify the
reference date.  If omitted, the server uses today's date in UTC.

```
run_funding(request, pk)
├── parse optional "as_of" date from request body
└── fund_account(account, as_of, system_user)   # kinds=None → all events
      [returns FundingReport]
    if report.busy:
        return 409 {"detail": "Funding is already running..."}
    if nothing happened (transfers=0, no occurrence transitions, no skips):
        return 409 {"detail": "No funding events are due..."}
    return 200 {transfers, occurrences_completed, occurrences_partial,
                warnings, skipped_budgets}
```

`FUNDING_COMPLETE` is never sent for API-triggered runs.  However,
`RECURRING_BUDGET_REFRESHED` is still emitted from inside
`_process_recur_event` for every recur event that runs through this path.

### 5.3 Management command

**File:** `app/moneypools/management/commands/fund_budgets.py`

```
manage.py fund_budgets [--account PATTERN] [--date YYYY-MM-DD] [--dry-run]
```

```
Command.handle
├── resolve accounts (all or one by pattern)
└── for each account:
      fund_account(account, today, actor)   # kinds=None → all events
        [returns FundingReport]
      if not dry_run and report.funded_budgets:
          notify_for(account, FUNDING_COMPLETE, {...})
      print per-account summary line (BUSY / OK / skipped counts)
```

`--dry-run` calls `_dry_run_report()` instead of `fund_account`.  It
replicates event collection and paused-budget detection without writing
any rows or touching the `FundingEventOccurrence` table.


---

## 6. `fund_account` — the engine

**File:** `app/moneypools/service/funding.py:fund_account`

```python
def fund_account(
    account: BankAccount,
    today: date,
    actor: User,
    kinds: set[EventKind] | None = None,
) -> FundingReport:
```

Steps in order:

1. **Acquire lock.**  `acquire_lock(account.lock_key, blocking=False)` —
   if another worker holds the lock, sets `report.busy = True` and
   returns immediately.

2. **Load budgets.** `Budget.objects.filter(bank_account=account, archived=False).select_related("fillup_goal")`.

3. **Collect events.** `_collect_events(budgets, today)` — returns an
   unsorted list of `FundingEvent` objects.

4. **Filter by kinds** (if `kinds` is given).  Return early if no events.

5. **Sort events** by `sort_key()`: `(date asc, FUND before RECUR, budget.id asc)`.

6. **Load Unallocated budget.**  Return early with a warning if missing.

7. **Instantiate occurrences.**  `_instantiate_occurrences(events)` —
   `get_or_create` a `FundingEventOccurrence` per event.  Existing PARTIAL
   rows carry forward; new events start as PENDING.

8. **Dispatch per event.**  For each event:
   - If the occurrence is already COMPLETE or SKIPPED: skip (no-op).
   - `_close_prior_incomplete(budget, kind, ev.date)` — mark any earlier
     PENDING/PARTIAL occurrences of the same (budget, kind) as SKIPPED.
   - If `budget.paused`: mark occurrence SKIPPED, append name to
     `report.skipped_budgets`, skip.
   - If `FUND`: call `_process_fund_event(ev, occ, account, unallocated, actor, report)`.
   - If `RECUR`: call `_process_recur_event(ev, occ, account, actor, report)`.

9. **Return** the `FundingReport`.


### 6.1 `_collect_events`

**File:** `funding.py:_collect_events`

For each non-archived budget:

- Skips `ASSOCIATED_FILLUP_GOAL` (funded indirectly via parent's fund events).
- Skips completed `GOAL` budgets.
- Computes `fund_after`:
  - If `last_funded_on` is set: use it.
  - Otherwise: `prev_recurrence_boundary(funding_schedule, created_at.date()) - 1 day`.
    (Anchors to the most recent schedule boundary on or before creation to
    avoid silently skipping events that fell between DTSTART and created_at.)
- **Clamps** `fund_after = min(fund_after, today - 1)` so today's event
  always fires regardless of pointer position.
- Calls `enumerate_schedule(funding_schedule, fund_after, today)` → dates
  in `(fund_after, today]`.
- For `RECURRING` budgets with a `recurrence_schedule`: same logic using
  `last_recurrence_on`, producing `RECUR` events.


### 6.2 `_process_fund_event`

**File:** `funding.py:_process_fund_event`

1. Determine target: `budget.fillup_goal` for RECURRING, else `budget`.
2. `refresh_from_db()` on unallocated, target, and budget.
3. `intended = strategy.intended_for_event(budget, ev.date, kind=FUND)`.
4. `already_moved` = sum of amounts on existing system FUND ITXs where
   `dst_budget=target` and `system_event_date=ev.date`.
5. `net = max(0, intended - already_moved)`.
6. If `net <= 0`: mark occurrence COMPLETE (intended already covered),
   advance `last_funded_on`, return.
7. `internal_transaction_svc.create(...)` in an atomic block —
   `system_event_kind=FUND`, `system_event_date=ev.date`,
   `effective_date=ev.date`.  The full `net` amount is transferred
   regardless of the Unallocated balance.  Unallocated may go negative
   when a deposit is still pending at fund time; this is expected to
   self-correct when the deposit posts (see §5.0 for the design rationale).
8. Mark occurrence COMPLETE, advance `last_funded_on`.
9. Append a budget entry to `report.funded_budgets`.

`last_funded_on` always advances on the first pass of a FUND event.
The `already_moved` formula (step 4) prevents double-funding on same-day
re-runs.


### 6.3 `_process_recur_event`

**File:** `funding.py:_process_recur_event`

1. Get `fillup = budget.fillup_goal`.  If missing: mark occurrence COMPLETE
   and return (defensive; should not occur).
2. `refresh_from_db()` on budget and fillup.
3. **Reset `complete=False`** at cycle start (the new cycle begins on the
   recur date, so the prior cycle's completion latch is cleared).
4. `intended = strategy.intended_for_event(budget, ev.date, kind=RECUR)`.
5. `already_moved` = sum of amounts on existing system RECUR ITXs where
   `dst_budget=budget` and `system_event_date=ev.date`.
6. `net = max(0, intended - already_moved)`.
7. If `net > 0`:
   - If fillup balance ≤ 0: warn, no transfer.
   - Else: `transfer = min(net, fillup_available)`, warn if capped.
   - `internal_transaction_svc.create(...)` in atomic block —
     `system_event_kind=RECUR`, `system_event_date=ev.date`.
8. Write `complete=(budget.balance >= target_balance)`.
9. Mark occurrence COMPLETE and advance `last_recurrence_on`
   **unconditionally** — even when no transfer occurred.  RECUR is
   one-shot: the cycle ends regardless of how much the fill-up had.
10. **Always** call `notify_for(account, RECURRING_BUDGET_REFRESHED, {...})`.


### 6.4 `internal_transaction_svc.create`

**File:** `app/moneypools/service/internal_transaction.py:create`

All balance mutations flow through this function to maintain budget-balance
invariants:

1. **Acquire sorted locks** on both budgets by UUID to prevent deadlocks.
2. **Atomic block**: refresh both budgets, debit `src_budget.balance`,
   credit `dst_budget.balance`.
3. Update `funded_amount` for GOAL budgets (credits increase, debits
   decrease).
4. **Sticky latch**: if `dst_budget` is GOAL, not yet complete, and
   `funded_amount >= target_balance > 0`, set `complete=True`.
5. Create the `InternalTransaction` row with `src_budget_balance` and
   `dst_budget_balance` snapshots.
6. Post-commit: call `alloc_svc.recalculate_from_dt` on both budgets and
   `alloc_svc.recalculate_itx_snapshots_from_dt` for both.


### 6.5 `_instantiate_occurrences`

**File:** `funding.py:_instantiate_occurrences`

`get_or_create` a `FundingEventOccurrence` for every event in the
enumerated list.  New rows are created with `status=PENDING`; existing
rows (e.g. PARTIAL from a prior run) are returned unchanged so their
state carries forward.

Returns a `dict[(budget_id_str, kind_value, scheduled_date)]` →
`FundingEventOccurrence` so the processing loop can look up each event's
occurrence without re-querying.


### 6.6 `_close_prior_incomplete`

**File:** `funding.py:_close_prior_incomplete`

Bulk-updates all PENDING/PARTIAL occurrences of the given `(budget, kind)`
with `scheduled_date < before_date` to SKIPPED.  Called just before each
event is dispatched so that at most one occurrence per `(budget, kind)` is
active at any time.


### 6.7 `_mark_occurrence_complete` / `_mark_occurrence_partial`

**File:** `funding.py`

`_mark_occurrence_complete` — sets `status=COMPLETE`, `completed_at=now()`,
and advances `Budget.last_funded_on` (FUND) or `Budget.last_recurrence_on`
(RECUR).  Increments `report.occurrences_completed`.

`_mark_occurrence_partial` — sets `status=PARTIAL` (idempotent; no-op if
already PARTIAL).  Increments `report.occurrences_partial`.


---

## 7. State at start of day

**File:** `app/moneypools/service/funding_strategy.py:state_at_start_of_D`

```python
def state_at_start_of_D(budget: Budget, D: date) -> tuple[Money, Money]:
```

Strategy methods call this to get `(balance_0, funded_amount_0)` — the
budget's state before any system-issued events on or after `D`.

```
S(budget, D) = system ITXs touching budget with system_event_date >= D

balance_0       = current_balance       - Σ signed_amount(budget) over S
funded_amount_0 = current_funded_amount - Σ signed_amount(budget) over S

signed_amount(budget) = +itx.amount if itx.dst_budget == budget
                        -itx.amount if itx.src_budget == budget
```

The `>=` (not `==`) is critical for two scenarios:

- **Same-day re-run**: rolls back the earlier run's ITX for date `D`, so
  `intended` is recomputed against the same pre-event baseline.  The
  `already_moved` formula then fills only what is still outstanding.
- **Multi-day catch-up**: when processing day `D+1` after `D` was
  processed in the same run, `D`'s ITX is not rolled back (it has
  `system_event_date = D < D+1`), so `D+1` correctly sees `D`'s deposit
  already applied.


---

## 8. Idempotency and same-day re-run mechanics

For each event `(budget, D, kind)`:

```
already_moved = Σ itx.amount for system ITXs where
                    dst_budget == target
                    system_event_kind == kind
                    system_event_date == D

net = max(0, intended_for_D - already_moved)
```

- **No-op re-run**: occurrence is COMPLETE → loop skips it immediately.
- **Same-day re-run (FUND)**: `already_moved == intended` → `net = 0` →
  no transfer; occurrence remains COMPLETE.  The full intended amount was
  already moved on the first pass.
- **RECUR is one-shot**: once COMPLETE (always after first pass),
  the occurrence is terminal and is never retried, even if the fill-up
  was short.  The next cycle starts fresh.
- **Pointer semantics**: `last_funded_on` / `last_recurrence_on` advance
  when `_mark_occurrence_complete` is called.  For FUND events this is
  always on the first pass.


---

## 9. Pointer semantics

`Budget.last_funded_on` and `Budget.last_recurrence_on` track the last
date the engine marked each event type COMPLETE.

**Initial state** (`budget_svc.create`): both pointers are set to
`created_at.date() - 1`.  This ensures the first scheduled event fires on
its scheduled date.

**Pause**: paused budgets have their occurrences marked SKIPPED.  Pointers
do **not** advance while the budget is paused.

**Unpause** (`budget_svc.update`): when a budget is unpaused, both
pointers are reset to `today - 1`.  This drops any events that fell during
the pause without replay (the SKIPPED occurrences from the pause period
remain in the DB but are terminal and will not be re-processed).  The
service emits a warning per missed recurrence boundary.

**Archive** (`budget_svc.archive`): drains any balance in the fill-up back
to Unallocated via a system ITX with `system_event_kind=None`, then marks
both the fill-up and the Recurring as archived.

**Unclamped catch-up**: `_collect_events` clamps `fund_after` to
`today - 1`, so today always fires.  Events in `(last_pointer, today)` are
catch-up events for missed days.


---

## 10. Goal completion latch

Goal budgets track `funded_amount` — the running net of all ITXs touching
the budget (credits minus debits).  Spending via `TransactionAllocation`
does **not** affect `funded_amount`.

The latch is set inside `internal_transaction_svc.create` when the credit
pushes `funded_amount >= target_balance > 0`.  It is one-directional:
`complete` never resets via the engine (only at recur boundaries for
Recurring budgets, which is unrelated).

A completed Goal is excluded by `_collect_events` (`budget.complete` check)
and receives no further fund events.

When `internal_transaction_svc.delete` reverses a credit that crossed the
threshold, `funded_amount` drops but `complete` stays `True` (high-water
mark semantic).


---

## 11. Notification flow

Two notification kinds are defined in
`app/moneypools/notification_kinds.py` and registered in
`MoneyPoolsConfig.ready()`:

| Constant                     | Kind string                             | Fired from                      | When                                                                                       |
|------------------------------|-----------------------------------------|---------------------------------|--------------------------------------------------------------------------------------------|
| `RECURRING_BUDGET_REFRESHED` | `moneypools.recurring_budget_refreshed` | Inside `_process_recur_event`   | After every recur event (even partial or zero); fired by **all three entry points**        |
| `FUNDING_COMPLETE`           | `moneypools.funding_complete`           | Celery task wrapper or CLI only | After a full run with `report.funded_budgets` non-empty; **not fired by the API endpoint** |

The key distinction is where each notification originates:

- `RECURRING_BUDGET_REFRESHED` is called **inside the engine** (in
  `_process_recur_event`), so it fires regardless of which caller invoked
  `fund_account`.
- `FUNDING_COMPLETE` is called in the **wrapper code** around
  `fund_account` (in `_run_funding_task` for the Celery tasks, and in
  `Command.handle` for the CLI).  The REST API view has no such wrapper,
  so this notification is never sent for API-triggered runs.

`notify_for` (`app/notifications/service.py:notify_for`) fans out to all
registered recipients.  CRITICAL-priority notifications are dispatched
immediately via a Celery task; others are queued for the digest.


---

## 12. Helper modules

### `app/moneypools/service/schedules.py`

Pure date helpers over `django-recurrence`.  No DB access.

| Function                                        | Description                                                        |
|-------------------------------------------------|--------------------------------------------------------------------|
| `enumerate_schedule(sched, after, before)`      | Dates in `(after, before]`                                         |
| `prev_recurrence_boundary(sched, as_of)`        | Most recent occurrence on or before `as_of`; searches 2 years back |
| `next_recurrence_boundary(sched, from_date)`    | First occurrence on or after `from_date`; searches 2 years ahead   |
| `count_occurrences(sched, from_date, end_date)` | Count in `[from_date, end_date]`; minimum 1                        |

### `app/moneypools/service/shared.py`

`funding_system_user() -> User` — returns the non-loginable system user
identified by `settings.FUNDING_SYSTEM_USERNAME`.  Used as the `actor`
on all engine-issued InternalTransactions.

### `app/moneypools/service/budget.py`

`create`, `update`, `archive` — manage pointer initialisation, pause-
unpause logic, fill-up sibling lifecycle.  The funding engine does not
call these directly; they are invoked by the API views.

### `app/moneypools/service/funding.py:next_funding_info`

```python
def next_funding_info(budget: Budget, today: date | None = None) -> NextFundingInfo | None:
```

Returns a `NextFundingInfo(date, amount)` for the next scheduled event, or
`None` if none is due.  No import-freshness check; the caller supplies
context for display purposes only.

### `app/moneypools/models.py`

`EventKind` (StrEnum: `FUND` / `RECUR`) lives in `models.py` so that
`FundingEventOccurrence.kind` and the service-layer event discriminator
share a single declaration.  Both `models.py` and `funding_strategy.py`
define or import it from there; all other modules import from `models`.


---

## 13. Worked examples

### 13.1 Capped fund event with low Unallocated balance

Setup: Capped budget `C` with `T=$50`, `A=$20`, `B=$10`.
Fund event fires at 23:00 local time.  `Unallocated` has only `$5`
(a paycheck is pending and hasn't posted yet).

**Engine run:**

- `B_0 = 10 - 0 = 10` (no system ITXs on today yet).
- `intended = min(20, max(0, 50 - 10)) = 20`.
- `already_moved = 0`.
- `net = 20`.  Full amount transfers regardless of Unallocated balance.
- System ITX: `Unallocated -> C, $20, FUND, today`.
- Occurrence → **COMPLETE**.  `last_funded_on = today`.

Result: `C.balance = $30`.  `Unallocated.balance = -$15` (was $5, paid $20).

The negative balance is expected to self-correct when the pending deposit
posts and its `TransactionAllocation` credits Unallocated.  This assumes
the user has calibrated their funding amounts to not exceed their real
income.  If the funding amounts are larger than actual deposits, the
deficit compounds across funding cycles rather than self-correcting.

**User clicks "Run funding now"** (hits the API endpoint):

- `_collect_events` re-enumerates today's FUND event (via clamp).
- `_instantiate_occurrences` returns the existing **COMPLETE** occurrence.
- Main loop: status is COMPLETE → **no-op**.  No additional transfer.

Result: `C.balance` unchanged at $30.

### 13.2 Recurring recur event shortfall

Setup: Recurring `R` with `T=$200`, `B=$0`.  Fill-up `F` with `Fill_B=$120`.
Today is the recurrence date.

**First engine run — recur event:**

- `B_0(R) = 0 - 0 = 0`; `Fill_B_0 = 120 - 0 = 120`.
- `intended = max(0, 200 - 0) = 200`.
- `already_moved = 0`.
- `transfer = min(200, 120) = 120`.
- System ITX: `F -> R, $120, RECUR, today`.
- `complete = False` (120 < 200).
- Warning: "fill-up only had $120; needed $200; underfunded."
- Occurrence → **COMPLETE** (RECUR is one-shot regardless of fill-up shortfall).
- `last_recurrence_on = today`.
- `notify_for(RECURRING_BUDGET_REFRESHED, ...)` fires.

**User moves $80 from other budgets into the fill-up.**

**User clicks "Run funding now":**

- `_collect_events` re-enumerates today's RECUR event (via clamp).
- `_instantiate_occurrences` returns the existing **COMPLETE** occurrence.
- Main loop: status is COMPLETE → **no-op**.  No additional transfer.

Post-run: `R.balance = $120`.  The remaining $80 in the fill-up carries
into the next cycle; it will reduce the prorated fund-event amounts for
the period leading up to the next recurrence date.

### 13.3 Engine misses Tuesday; Wednesday catches up

Setup: Goal `G`, `T=$100`, funded_amount=0, `TARGET_DATE`, weekly funding,
target next Friday.  `last_funded_on = Sunday`.

Tuesday: engine does not run (server restart).

Wednesday engine run — events in `(Sunday, Wednesday]`: Mon, Tue, Wed.

- **Monday** (`N_to_target` Mon→Fri = 5):
  `F_0(Mon) = 0 - 0 = 0`, `intended = 100 / 5 = 20`.
  transferred=$20, COMPLETE, `last_funded_on = Monday`.

- **Tuesday** (`N_to_target` Tue→Fri = 4):
  `F_0(Tue) = current(20) - Σ(system ITXs date >= Tue) = 20 - 0 = 20`.
  `intended = (100 - 20) / 4 = 20`.
  transferred=$20, COMPLETE, `last_funded_on = Tuesday`.

- **Wednesday** (`N_to_target` Wed→Fri = 3):
  `F_0(Wed) = current(40) - Σ(system ITXs date >= Wed) = 40 - 0 = 40`.
  `intended = (100 - 40) / 3 = 20`.
  transferred=$20, COMPLETE, `last_funded_on = Wednesday`.

Three equal transfers; target stays on track.  No double-counting.

### 13.4 Pause across recurrence boundary

Setup: Recurring `R`, funding twice monthly (15th and last day), recur on
1st of month.  User pauses on Jan 16.  User unpauses on Apr 3.

During pause (each engine run):

- Events for `R` in range are enumerated; occurrences are created as
  PENDING on first encounter and then marked **SKIPPED**.
- `last_funded_on` and `last_recurrence_on` do **not** advance.

On unpause (`budget_svc.update`):

- Sets `paused = False`.
- Sets `last_funded_on = Apr 2`, `last_recurrence_on = Apr 2`.
- Emits one warning per missed recur boundary: Feb 1, Mar 1, Apr 1.

Apr 3 engine run: no events in `(Apr 2, Apr 3]`.  No-op.

Apr 15 fund event:

- `Fill_B_0` = whatever the fill-up currently holds.
- `N` = funding events Apr 15 through May 1 = 2 (Apr 15, Apr 30).
- `intended = (T - Fill_B_0) / 2`.


---

## 14. Implementation notes

### Dead `is_complete()` methods in `funding_strategy.py`

`FundingStrategy.is_complete()` is declared as an abstract method on the
base class and implemented by all three concrete strategies.  However, it
is **never called** from any production code.  Completion checking in
`_collect_events` reads `budget.complete` directly.  These methods are
dead code and can be removed.
