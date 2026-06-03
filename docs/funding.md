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
account: re-running it any number of times on the same day is safe and
self-correcting.

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

The engine recognises two event kinds:

- **Fund event** — fires on `budget.funding_schedule`.  For Goal and
  Capped, the destination is the budget itself.  For Recurring, the
  destination is the fill-up sibling (not the Recurring budget directly).
- **Recur event** — fires on `budget.recurrence_schedule`.  Only
  Recurring budgets have these.  Source is the fill-up; destination is
  the Recurring budget.

When a fund event and a recur event fall on the same day for the same
Recurring budget, the **fund event runs first**.  This guarantees the
fill-up has its maximum available balance before the recur sweep.

The sort key is `(date asc, FUND before RECUR, budget.id asc)`.
Implemented at `funding.py:FundingEvent.sort_key()`.


---

## 4. Per-event amount formulas

Each budget type has a strategy class in
`app/moneypools/service/funding_strategy.py` that computes the intended
transfer amount for a single event.  All formulas operate on
**state at the start of the event date** — defined in §6.

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

### 5.1 Celery Beat scheduler

**File:** `app/moneypools/tasks.py`

`schedule_funding_runs` is registered in
`app/config/celery_app.py:MANAGED_PERIODIC_TASKS` with crontab
`{"minute": "0,30"}` — it fires every 30 minutes, all day.

On each tick it:

1. Iterates all `BankAccount` rows (prefetching owners).
2. Reads the first owner's IANA timezone (`owner.timezone`).
3. **Unconditionally** appends `(account_id, local_date_str, owner_tz)` to
   `fund_accounts`.
4. Appends to `recur_accounts` only when local time is in
   `[03:00, 03:30)`.
5. Spreads tasks evenly across up to 30 minutes to avoid a DB stampede.

Two Celery tasks are dispatched:

```
schedule_funding_runs
├── fund_one_account(account_id, local_date_str, owner_tz)
│     └── _run_funding_task(..., kinds={EventKind.FUND}, ...)
│           └── fund_account(account, today, actor, kinds={FUND}, tz=owner_tz)
│                 [returns FundingReport]
│           if report.funded_budgets:
│               notify_for(account, FUNDING_COMPLETE, {...})
│
└── recur_one_account(account_id, local_date_str, owner_tz)   # 03:00–03:30 only
      └── _run_funding_task(..., kinds={EventKind.RECUR}, ...)
            └── fund_account(account, today, actor, kinds={RECUR}, tz=owner_tz)
                  [returns FundingReport]
            if report.funded_budgets:
                notify_for(account, FUNDING_COMPLETE, {...})
```

Because `kinds` is a filter, the import-freshness gate is evaluated only
against the filtered event set.  The FUND pass is not gated on RECUR event
dates and vice versa.

`_run_funding_task` handles account lookup, system-user lookup, and
`local_date_str` parsing before calling `fund_account`.

### 5.2 REST API endpoint

**File:** `app/moneypools/api/v1/views.py:BankAccountViewSet.run_funding`

`POST /api/v1/bank-accounts/<id>/run-funding/`

```
run_funding(request, pk)
├── parse optional "as_of" date from request body
└── fund_account(account, as_of, system_user)   # kinds=None → all events
      [returns FundingReport]
    return {deferred, transfers, warnings, skipped_budgets}
```

The view itself does not call `notify_for`, so `FUNDING_COMPLETE` is never
sent for API-triggered runs.  However, `RECURRING_BUDGET_REFRESHED` is
still emitted from inside `_process_recur_event` for every recur event
that runs through this path.  It also processes all event kinds together
(no `kinds` filter).

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
      print per-account summary line
```

`--dry-run` calls `_dry_run_report()` instead of `fund_account`.  It
replicates the import-freshness gate and event collection without writing
any rows.


---

## 6. `fund_account` — the engine

**File:** `app/moneypools/service/funding.py:fund_account`

```python
def fund_account(
    account: BankAccount,
    today: date,
    actor: User,
    kinds: set[EventKind] | None = None,
    tz: str | None = None,
) -> FundingReport:
```

Steps in order:

1. **Load budgets.** `Budget.objects.filter(bank_account=account, archived=False).select_related("fillup_goal")`.

2. **Collect events.** `_collect_events(budgets, today)` — returns an
   unsorted list of `FundingEvent` objects.

3. **Filter by kinds** (if `kinds` is given).

4. **Import-freshness gate.**  Computes `gate_date = max(ev.date)` across
   filtered events.  Checks whether `account.last_posted_through >= gate_date`
   OR `account.last_imported_at (localized) >= gate_date`.  If neither
   passes, sets `report.deferred = True` and returns immediately — no
   transfers, no pointer advances.

5. **Sort events** by `sort_key()`: `(date asc, FUND before RECUR, budget.id asc)`.

6. **Dispatch per event.**  For each event:
   - If `budget.paused`: advance the relevant pointer to `ev.date`,
     append name to `report.skipped_budgets`, skip.
   - If `FUND`: call `_process_fund_event(ev, account, unallocated, actor, report)`.
   - If `RECUR`: call `_process_recur_event(ev, account, actor, report)`.

7. **Return** the `FundingReport`.


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
6. If `net <= 0`: advance `last_funded_on`, return (no-op).
7. If unallocated balance ≤ 0: warn, advance pointer, return.
8. If `net > available`: warn, cap `net` to available balance.
9. `internal_transaction_svc.create(...)` in an atomic block —
   `system_event_kind=FUND`, `system_event_date=ev.date`,
   `effective_date=ev.date` (for correct timeline placement on backfill).
10. Advance `last_funded_on` unconditionally.
11. Append a budget entry to `report.funded_budgets`.


### 6.3 `_process_recur_event`

**File:** `funding.py:_process_recur_event`

1. Get `fillup = budget.fillup_goal`.
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
8. Write `last_recurrence_on=ev.date` and
   `complete=(budget.balance >= target_balance)` **unconditionally** — even
   when the transfer was zero.
9. **Always** call `notify_for(account, RECURRING_BUDGET_REFRESHED, {...})`.


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

`net` is capped by the source budget's available balance.

- **No-op re-run**: `already_moved == intended` → `net = 0` → no new ITX.
- **Partial re-run** (source was empty): `already_moved < intended` → `net`
  fills the remainder.
- **Pointer semantics**: the pointer (`last_funded_on` / `last_recurrence_on`)
  advances unconditionally after each event, whether or not a transfer
  occurred.  **Under-funded events are not retried** on subsequent days.
  The same-day re-run window is the user's only opportunity to top up.
  Paused budgets consume their events (pointer advances) so they do not
  accumulate a backlog during the pause.


---

## 9. Pointer semantics

`Budget.last_funded_on` and `Budget.last_recurrence_on` track the last
date the engine processed each event type.

**Initial state** (`budget_svc.create`): both pointers are set to
`created_at.date() - 1`.  This ensures the first scheduled event fires on
its scheduled date.

**Pause-unpause** (`budget_svc.update`): when a budget is unpaused, both
pointers are reset to `today - 1`.  This drops any events that fell during
the pause without replay.  The service emits a warning per missed
recurrence boundary.

**Archive** (`budget_svc.archive`): drains any balance in the fill-up back
to Unallocated via a system ITX with `system_event_kind=None`, then marks
both the fill-up and the Recurring as archived.

**Unclamped catch-up**: `_collect_events` clamps `fund_after` to
`today - 1`, so today always fires.  Events in `(last_pointer, today)` are
catch-up events for missed days.


---

## 10. Import-freshness gate

Before processing any events, `fund_account` checks whether the account's
bank data is current:

```
gate_date = max(ev.date for ev in events)

passes if:
    account.last_posted_through >= gate_date
  OR
    account.last_imported_at (localized to owner_tz) >= gate_date
```

If neither condition holds, `report.deferred = True` is returned with no
transfers and no pointer advances.  This prevents funding against a stale
view of the account.

The gate is evaluated against the filtered event set, so the FUND pass (all
ticks) is not gated on RECUR event dates, and vice versa.


---

## 11. Goal completion latch

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

## 12. Notification flow

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

## 13. Helper modules

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


---

## 14. Worked examples

### 14.1 Capped under-funded, user fixes, re-runs

Setup: Capped budget `C` with `T=$50`, `A=$20`, `B=$10`.
Fund event fires today.  `Unallocated` has only `$5`.

**First engine run:**

- `B_0 = 10 - 0 = 10` (no system ITXs on today yet).
- `intended = min(20, max(0, 50 - 10)) = 20`.
- `already_moved = 0`.
- `transfer = max(0, 20 - 0) = 20`; capped by `Unallocated = $5` → `$5`.
- System ITX: `Unallocated -> C, $5, FUND, today`.
- `last_funded_on = today`.
- Warning: "wanted $20, only $5 available; capped."

**Later: user moves $40 from another budget to `Unallocated`.**

**User clicks "Run funding now"** (hits the API endpoint):

- `B_0 = current($15) - Σ(signed for FUND ITXs with date >= today) = 15 - 5 = $10`.
- `intended = min(20, max(0, 50 - 10)) = 20`.
- `already_moved = $5`.
- `transfer = max(0, 20 - 5) = 15`; available = $40, so $15.
- System ITX: `Unallocated -> C, $15, FUND, today`.
- `last_funded_on` remains at today.

Result: `C.balance = $30`.  Total system deposits today = $20 = `A`.

**Next engine run:** `last_funded_on = today`; tomorrow's events are the
next in range.  Yesterday's event is not revisited.

### 14.2 Recurring recur event shortfall, user moves money to fill-up

Setup: Recurring `R` with `T=$200`, `B=$0`.  Fill-up `F` with `Fill_B=$120`.
Today is the recurrence date.

**First engine run — recur event:**

- `B_0(R) = 0 - 0 = 0`; `Fill_B_0 = 120 - 0 = 120`.
- `intended = max(0, 200 - 0) = 200`.
- `already_moved = 0`.
- `transfer = min(200, 120) = 120`.
- System ITX: `F -> R, $120, RECUR, today`.
- `last_recurrence_on = today`, `complete = False` (120 < 200).
- Warning: "fill-up only had $120; needed $200; underfunded."
- `notify_for(RECURRING_BUDGET_REFRESHED, ...)` fires.

**User moves $80 from other budgets into the fill-up (manual ITX).**
After: `Fill_B = $80`, `R.balance = $120`.

**User clicks "Run funding now":**

- `B_0(R) = current($120) - Σ(RECUR ITXs with date >= today) = 120 - 120 = 0`.
- `Fill_B_0 = current($80) - Σ(RECUR src ITXs with date >= today) = 80 - (-120) = 200`.
  (The sign: F was src, so signed_amount for F = -120; rolling back subtracts that.)
- `intended = max(0, 200 - 0) = 200`.
- `already_moved = $120`.
- `net = 200 - 120 = 80`; capped by current `Fill_B = $80` → $80.
- System ITX: `F -> R, $80, RECUR, today`.
- `complete = True` (200 >= 200).
- `notify_for(RECURRING_BUDGET_REFRESHED, ...)` fires again.

Post-transfer: `R.balance = $200`, `Fill_B = $0`.

**Next engine run:** yesterday's recur is not revisited.  Fund events
continue accumulating into the fill-up for the next cycle.

### 14.3 Engine misses Tuesday; Wednesday catches up

Setup: Goal `G`, `T=$100`, funded_amount=0, `TARGET_DATE`, weekly funding,
target next Friday.  `last_funded_on = Sunday`.

Tuesday: engine does not run (server restart).

Wednesday engine run — events in `(Sunday, Wednesday]`: Mon, Tue, Wed.

- **Monday** (`N_to_target` Mon→Fri = 5):
  `F_0(Mon) = 0 - 0 = 0`, `intended = 100 / 5 = 20`.
  ITX $20, `last_funded_on = Monday`.

- **Tuesday** (`N_to_target` Tue→Fri = 4):
  `F_0(Tue) = current(20) - Σ(system ITXs date >= Tue) = 20 - 0 = 20`.
  `intended = (100 - 20) / 4 = 20`.
  ITX $20, `last_funded_on = Tuesday`.

- **Wednesday** (`N_to_target` Wed→Fri = 3):
  `F_0(Wed) = current(40) - Σ(system ITXs date >= Wed) = 40 - 0 = 40`.
  `intended = (100 - 40) / 3 = 20`.
  ITX $20, `last_funded_on = Wednesday`.

Three equal transfers; target stays on track.  No double-counting.

### 14.4 Pause across recurrence boundary

Setup: Recurring `R`, funding twice monthly (15th and last day), recur on
1st of month.  User pauses on Jan 16.  User unpauses on Apr 3.

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

## 15. Implementation notes

### Stale module docstring in `tasks.py`

The module-level docstring of `app/moneypools/tasks.py` (lines 9–18)
states that `fund_one_account` is enqueued only in the `[23:00, 23:30)`
local-time window.  **This is incorrect.**  The current code in
`schedule_funding_runs` unconditionally appends every account to
`fund_accounts` on every tick; the `[23:00, 23:30)` window restriction
was removed when the scheduler was redesigned.  The docstring should be
updated to match.

### Dead `is_complete()` methods in `funding_strategy.py`

`FundingStrategy.is_complete()` is declared as an abstract method on the
base class and implemented by all three concrete strategies.  However, it
is **never called** from any production code.  Completion checking in
`_collect_events` reads `budget.complete` directly.  These methods are
dead code and can be removed.
