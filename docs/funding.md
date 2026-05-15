# Funding

This document is the design specification for mibudge's budget funding
system.  It defines the funding model unambiguously so that the
implementation, the tests, and any future contributor can reason about
each behavior in isolation.

The accompanying README section is a short summary; this document is
the authoritative reference.

## 1. Overview

**Funding** is the act of moving money from a bank account's
``Unallocated`` budget into other budgets on that same account, on a
schedule.  No real bank transfer happens -- funding is reallocation
within the virtual accounting layer.

The **funding engine** is a single function (``fund_account``) that
runs idempotently per bank account.  It is invoked:

- Automatically once per day at 3:00 AM UTC via the Celery beat task
  ``fund_all_accounts``.
- Manually via ``POST /api/v1/bank-accounts/<id>/run-funding/``.
- Manually via the importer CLI with ``--run-funding``.

The engine is **safely re-runnable any number of times in a single
day**.  Re-runs top up under-funded events without double-funding.
This is a first-class user scenario -- after a manual top-up of
``Unallocated``, the user can trigger the engine again and expect the
day's events to complete.


## 2. Budget types

There are exactly three user-facing budget types, plus one supporting
type:

| Type | Purpose | Has fill-up? | Funding types allowed |
|------|---------|--------------|------------------------|
| **Goal**             | One-shot accumulation toward a target | No  | ``TARGET_DATE``, ``FIXED_AMOUNT`` |
| **Capped**           | Perpetually topped up to a cap        | No  | ``FIXED_AMOUNT`` only             |
| **Recurring**        | Periodic budget that resets on a cycle | Yes (mandatory) | ``TARGET_DATE`` only |
| **Associated Fill-up** | Sibling of a Recurring; receives funding on the Recurring's schedule | n/a | n/a |

A Recurring budget always has exactly one Associated Fill-up
sibling, created automatically when the Recurring is created.

The Associated Fill-up is itself a Budget row, linked from the
Recurring via the existing ``Budget.fillup_goal`` FK.  It has no
funding_schedule or recurrence_schedule of its own -- it is funded and
drained entirely by the engine acting on its Recurring parent.

The ``Unallocated`` budget on each bank account is a fifth type for
bookkeeping (created automatically per account) and is never funded.


## 3. Event model

The engine processes two kinds of events:

- **Fund event** -- fires on ``budget.funding_schedule``.  For Goal
  and Capped, the destination is the budget itself.  For Recurring,
  the destination is the Recurring's fill-up sibling.
- **Recur event** -- fires on ``budget.recurrence_schedule``.  Only
  Recurring budgets have these.  The source is the fill-up sibling;
  the destination is the Recurring budget.

When both fire on the same date for the same Recurring budget, the
**fund event runs first**, then the recur event.  This guarantees the
fill-up has the maximum balance available before the recur sweeps it
into the Recurring.

Same-day ordering across budgets is by (date, fund-before-recur,
budget.id).  This matches the current ``FundingEvent.sort_key`` at
``app/moneypools/service/funding.py``.


## 4. The four funding rules

The engine's per-event "intended amount" is determined by the budget
type and (for Goal) the funding type.  All rules below operate on
**state at the start of the event date** -- defined precisely in
section 6.

Let:

- ``T`` = ``budget.target_balance``
- ``F`` = ``budget.funded_amount`` (Goal only; see section 5)
- ``B`` = ``budget.balance``
- ``A`` = ``budget.funding_amount`` (set only when funding_type is
  ``FIXED_AMOUNT``)
- ``Fill_B`` = ``budget.fillup_goal.balance`` (Recurring only)
- ``N_to_target`` = number of fund-schedule occurrences from today
  (inclusive) through ``target_date`` (inclusive), minimum 1
- ``N_in_cycle`` = number of fund-schedule occurrences from today
  (inclusive) through the next recurrence-schedule occurrence
  (inclusive), minimum 1

All subscripts ``_0`` denote "value at start of event date" (i.e.,
prior to any system-issued ITX with ``system_event_date >= D``).

### 4.1 Goal + ``FIXED_AMOUNT``

```
intended = min(A, max(0, T - F_0))
```

The budget receives ``A`` per fund event until ``F`` reaches ``T``.
Once ``F >= T`` the budget latches ``complete=True`` (section 5) and
receives no further fund events.

### 4.2 Goal + ``TARGET_DATE``

```
if today <= target_date:
    intended = max(0, T - F_0) / N_to_target
else:
    intended = max(0, T - F_0)        # close the gap on the next event
```

After ``target_date`` passes, ``N_to_target`` is no longer
well-defined -- no schedule occurrences remain in the
``today..target_date`` window -- so the formula degenerates to direct
gap closure as written above.  Every remaining fund event after the
deadline transfers the full remaining gap and the engine emits a
warning per event so the user can react.  No retroactive events are
generated -- the next scheduled fund event simply closes the gap.

### 4.3 Capped

```
intended = min(A, max(0, T - B_0))
```

Capped is purely gap-based.  It is never marked complete; the field
is unused for this type.

### 4.4 Recurring -- fund event (Unallocated -> fillup)

```
intended = max(0, T - Fill_B_0) / N_in_cycle
```

Money goes to the fill-up, not the Recurring parent.  The formula
prorates the remaining-to-target gap across all fund events still due
before the next recur date (inclusive of today, inclusive of the day
before the next recur date).

### 4.5 Recurring -- recur event (fillup -> Recurring)

```
intended = min(max(0, T - B_0), Fill_B_0)
```

On the recurrence boundary, the fill-up tops the Recurring back up to
its target.  Any excess in the fill-up stays in the fill-up -- it is
the head start for the next cycle.  If the fill-up does not cover the
gap, the Recurring is left under-funded for the cycle and a warning is
emitted; the engine will not retry until the next recur date.


## 5. ``funded_amount`` and Goal completion

This redesign introduces a new field on ``Budget``:

```
funded_amount: MoneyField, default 0
```

**Definition.**  For a Goal:

```
funded_amount = sum(itx.amount for itx where itx.dst_budget == self)
              - sum(itx.amount for itx where itx.src_budget == self)
```

That is: the running sum of all InternalTransactions touching this
budget, **without regard to whether the ITX was issued by the funding
engine or by a user**.  Manual transfers count.  System transfers
count.  Spending via ``TransactionAllocation`` does **not** count.

For non-Goal budget types, ``funded_amount`` is unused and remains 0.
The implementation must not branch on ``funded_amount`` for Capped or
Recurring; those types use ``balance`` directly.

**Invariant** (Goal only):

```
balance = funded_amount - spent_amount
```

where ``spent_amount`` is a derived property (not a stored field) over
``TransactionAllocation`` rows pointing at this budget.  ``verify_balances``
must validate this invariant for every Goal.

**Sticky completion latch.**  A Goal's ``complete`` flag is a one-way
latch:

- It flips ``False -> True`` the moment ``funded_amount >= target_balance``.
- It **never** resets, even if a subsequent ITX (manual or system)
  drops ``funded_amount`` below ``target_balance``.
- A completed Goal receives no further fund events.

**Where the latch is enforced.**  In
``internal_transaction_svc.create()``, after the credit posts and
``funded_amount`` has been updated, the service checks whether
``dst_budget`` is a Goal whose ``funded_amount`` has just crossed the
threshold and, if so, sets ``complete=True``.  The latch is **not**
implemented in ``Budget.pre_save``: a pre_save signal fires on every
save, but the latch must only fire on the ITX that crossed the
threshold.

**On ITX deletion.**  When ``internal_transaction_svc.delete()``
reverses a credit that previously crossed the threshold,
``funded_amount`` decrements but ``complete`` stays True.  This is
intentional and consistent with the "high-water mark" semantic.


## 6. State at start of day

The engine's intended-amount rules in section 4 read state "at the
start of the event date" rather than current state.  This makes the
math idempotent on same-day re-runs and on multi-day catch-up.

Concretely, for a budget ``X`` and an event date ``D``:

```
B_0(X, D)   = X.balance       - sum(itx.signed_amount(X) for itx in S(X, D))
F_0(X, D)   = X.funded_amount - sum(itx.signed_amount(X) for itx in S(X, D))
Fill_B_0(R, D) = B_0(R.fillup_goal, D)
```

where ``S(X, D)`` is the set of **system-issued** InternalTransactions
touching budget ``X`` with ``system_event_date >= D``, and
``signed_amount(X)`` returns ``+amount`` if ``itx.dst_budget == X``
and ``-amount`` if ``itx.src_budget == X``.

Note the ``>=``: when catching up multiple missed days in order, the
formula must roll back **all** system ITXs from the event being
processed onward, not just the ones on that exact date.  Otherwise the
second day's intended sees the first day's transfer already applied
and under-funds.

This formula assumes two invariants the engine must maintain: events
are processed in **strict date-ascending order**, and "start of D"
means "after all events with date ``< D`` in this run have been
fully applied."  The ``>=`` rolls back ITXs issued for date ``D``
(including any from a previous engine run on the same calendar day,
which gives same-day re-run idempotency) while leaving ITXs for prior
dates ``D' < D`` applied (which gives sequential multi-day catch-up).


## 7. Same-day re-run mechanics

Each engine run computes, for each event ``(X, D)``:

```
already_moved(X, D, K) = sum(itx.signed_amount(X)
                             for itx in system ITXs touching X
                             with system_event_date == D
                             and  system_event_kind == K)

transfer = max(0, intended_for_D - already_moved(X, D, K))
```

clamped further by the available balance of the source (``Unallocated``
for fund events, ``fillup_goal`` for recur events).

If ``transfer > 0`` the engine issues a system ITX (section 8).
Otherwise the event is a no-op.

This formula is self-correcting under all of:

- **Same-day re-run with no state change.** ``already_moved == intended``,
  ``transfer == 0``.  No-op.
- **Same-day re-run after a partial.** ``already_moved < intended``;
  ``transfer`` fills the remainder.
- **Same-day re-run after user manually moved money into the budget
  via a separate ITX.**  That ITX is not ``system_issued``, so it
  doesn't count against ``already_moved``.  Whether it affects
  ``intended`` depends on the rule: Goal+FIXED and Capped lower
  ``intended`` (because the gap closed); Goal+TARGET_DATE and
  Recurring fund lower ``intended`` proportionally; recur event
  lowers ``intended`` directly via the lower remaining gap.


## 8. The system-issued InternalTransaction

The engine issues InternalTransactions identified by their ``actor``
being the ``funding-system`` user (already in use today; see
``app/moneypools/service/funding.py::funding_system_user``).

Two new fields on ``InternalTransaction`` carry the event metadata:

```
system_event_kind: CharField(1) | null   # "F" = fund, "R" = recur, null = user-issued
system_event_date: DateField   | null    # the scheduled event date, null = user-issued
```

Both fields are populated **iff** ``actor == funding_system_user()``.
They are queried by ``already_moved`` (section 7) and by the
state-at-start-of-day rollback (section 6).

**Why not reuse ``effective_date``?**  ``effective_date`` drives
running-balance snapshot ordering in
``transaction_allocation_svc.recalculate_itx_snapshots_from_dt``.
Backdating a system ITX's ``effective_date`` to a missed Tuesday when
processing on Thursday would re-order snapshots on the destination
budget across intervening user activity.  We keep ``effective_date``
as wall-clock and use the separate ``system_event_date`` field for the
engine's "event date" concept.

**Why an explicit ``system_event_kind``?**  A Recurring budget can
have a fund event and a recur event on the same date.  Both touch the
fill-up.  Without a kind discriminator, ``already_moved`` for the recur
event would include the fund event's deposit into the fill-up and
under-transfer.

**API immutability.**  ``InternalTransactionViewSet`` already exposes
only Create/Retrieve/List -- update and delete are blocked at the
route level.  ``perform_create`` sets ``actor=request.user``
unconditionally, so a user cannot forge a system-issued ITX.  These
guarantees are preconditions of this design; the implementation must
not loosen them.


## 9. Pause, archive, resume

**Paused** budgets are skipped by the engine entirely: no fund events,
no recur events.

**Archived** budgets are skipped and cannot be unarchived.

**The pointer fields** -- ``Budget.last_funded_on`` and
``Budget.last_recurrence_on`` -- are the engine's per-day catch-up
markers.  The rules:

1. **Pointer advances unconditionally** after the engine processes an
   event.  Whether the transfer was full, partial, or zero (because
   ``Unallocated`` / fill-up was empty), the pointer moves to ``D``.
   This matches the user's "we consider this event over" intent:
   under-funded events are not retried on subsequent days; the missed
   amount is lost and the user gets a warning.
2. **Today's events are always processed**, regardless of pointer
   position.  Concretely, on every engine run the engine processes:

   - **Catch-up events**: scheduled events in ``(last_pointer, today)``
     -- exclusive of today.  These exist only when the daemon missed
     a previous day's run.
   - **Today's events**: scheduled events whose date is ``today``,
     processed even if the pointer is already at today.

   This is what supports the same-day-re-run scenarios in section 14:
   the engine re-evaluates today's events on every invocation, and
   the ``intended - already_moved`` formula (section 7) makes the
   re-evaluation idempotent.  A fully-satisfied event yields
   ``transfer = 0`` (no-op); a partially-satisfied one yields a top-up.

3. **Pause-unpause.**  When a budget is unpaused, the budget update
   service (``budget_svc.update``, or wherever ``paused`` flips from
   True to False) sets both ``last_funded_on`` and
   ``last_recurrence_on`` to ``today - 1 day``.  This drops any
   events that fell during the pause window without replay.  It must
   happen in the service layer that handles the pause flip, **not**
   at the next engine tick.

**Pause across a recurrence boundary.**  If a Recurring budget was
paused on Jan 16 and unpaused on Apr 3, the Feb 1, Mar 1, and Apr 1
recur events are lost.  The Recurring keeps whatever balance it had
when paused; the fill-up keeps whatever balance it had when paused.
On the next recur date after unpause (May 1), the normal rule
applies.  The engine emits one warning per missed recur boundary as
part of the unpause path so the user is informed.

**Initial pointer state for new budgets.** On creation,
``last_funded_on`` and ``last_recurrence_on`` are set to
``created_at.date() - 1 day``.  This ensures the first scheduled event
fires on its scheduled date rather than being skipped because the
pointer was already at or past it.

**Archive of a Recurring.** Archiving the Recurring parent
automatically archives its fill-up sibling.  Any remaining balance on
the fill-up is swept back to Unallocated via a system-issued ITX
issued by ``budget_svc.archive`` (not the engine).  This system ITX
uses ``system_event_kind=null`` and ``system_event_date=null`` because
it is not an event-driven transfer; the actor is the
``funding-system`` user for auditability.


## 10. Import-freshness gate

Preserved from current behavior: before the engine processes events,
it checks ``account.last_posted_through``.  If the latest due event
date is after that, **the entire run is deferred** -- no transfers
made, no pointers moved.  ``FundingReport.deferred=True`` is returned.

This is engine-level, not per-event.  It prevents the engine from
funding budgets against a stale view of bank activity.


## 11. Constraints (enforced as ``Budget.clean()`` validators)

| Constraint | Applies to |
|---|---|
| ``funding_type == TARGET_DATE``                     | Recurring |
| ``funding_type == FIXED_AMOUNT``                    | Capped |
| ``target_date IS NULL``                              | Recurring, Capped |
| ``target_date`` required iff ``funding_type == TARGET_DATE`` | Goal |
| ``funding_amount`` required iff ``funding_type == FIXED_AMOUNT`` | Goal, Capped |
| ``recurrence_schedule IS NULL`` iff not Recurring   | All |
| ``fillup_goal IS NOT NULL`` iff Recurring            | All |
| ``budget_type == ASSOCIATED_FILLUP_GOAL`` implies exactly one Recurring points at it | Fillups |
| ``funding_amount`` is unused for Recurring          | Recurring |
| ``funded_amount`` is unused for Capped and Recurring | All |
| ``complete`` is never set for Capped (enforced by removing the signal toggle in ``signals.py:90-108``, not by ``clean()``) | Capped |

Database-level CHECK constraints back the most important of these
where Django supports them via ``constraints = [...]`` on Meta.


## 12. Architecture

The funding code is reorganized into three modules under
``app/moneypools/service/``:

- **``funding.py``** -- the engine.  Exposes ``fund_account``,
  ``next_funding_info``, ``funding_system_user``,
  ``funding_event_dates``.  Responsible for: import-freshness gate,
  event enumeration, per-event dispatch to a strategy, pointer
  advancement, report assembly.
- **``funding_strategy.py``** -- one ``FundingStrategy`` base class
  plus ``GoalStrategy``, ``CappedStrategy``, ``RecurringStrategy``.
  Each strategy implements:

  ```
  def intended_for_event(budget, event_date, *, kind) -> Money
  def is_complete(budget) -> bool
  ```

  Registered in a ``BUDGET_TYPE_TO_STRATEGY`` dict so the engine can
  dispatch by ``budget.budget_type``.
- **``schedules.py``** -- pure helpers over ``django-recurrence``:
  ``prev_recurrence_boundary``, ``next_recurrence_boundary``,
  ``count_occurrences``, ``enumerate_schedule``.  No DB access.

The current ``app/moneypools/service/funding.py`` has all three roles
mashed together.  Splitting them gives us testable, separately-mockable
units and makes the per-type behavior live in one place per type.


## 13. Migration plan

This is a single chain of Django migrations and a small data migration.

**Schema migrations:**

1. Add ``Budget.funded_amount`` (``MoneyField``, default 0,
   ``null=False``).
2. Add ``InternalTransaction.system_event_kind`` (``CharField(1)``,
   choices = ``(("F", "Fund"), ("R", "Recur"))``, null=True,
   default=None).
3. Add ``InternalTransaction.system_event_date`` (``DateField``,
   null=True, default=None).
4. Drop ``Budget.with_fillup_goal``.
5. Add ``Budget.clean()`` validators and ``Meta.constraints`` from
   section 11.

**Data migration:**

- For each ``Budget`` with ``budget_type == GOAL``:

  ```
  funded_amount = sum(itx.amount where itx.dst_budget == b)
                - sum(itx.amount where itx.src_budget == b)
  ```

  taken over **all** InternalTransactions, not just system ones.  For
  non-Goal budgets, leave at 0.

- For each ``InternalTransaction`` with
  ``actor == funding_system_user()``:

  - Infer ``system_event_kind`` from ``(src_budget, dst_budget)``
    topology: if ``src_budget == Unallocated``, it is a fund event
    (``"F"``); if ``dst_budget`` is a Recurring and
    ``src_budget == dst_budget.fillup_goal``, it is a recur event
    (``"R"``); otherwise the migration logs the row and leaves the
    fields null (operator inspects manually).
  - Set ``system_event_date = effective_date.date()`` if non-null,
    else ``created_at.date()``.

- For each ``Recurring`` budget with no ``fillup_goal`` (legacy
  ``with_fillup_goal=False`` rows): auto-create a sibling ``Budget``
  of type ``ASSOCIATED_FILLUP_GOAL``, set the parent's
  ``fillup_goal`` FK to it, log the migration.

- For each ``Capped`` budget with ``funding_type == TARGET_DATE`` or
  ``target_date IS NOT NULL``: the migration **errors out** and
  prints the list of offending budget IDs.  This must be resolved
  manually (data fix or budget reclassification) before the migration
  can re-run.

**Code removal:**

- Remove the ``Capped`` branch in
  ``app/moneypools/signals.py:90-108`` (the ``complete`` toggling
  block).
- Remove all references to ``with_fillup_goal``.


## 14. Worked examples

### 14.1 Capped under-funded, user fixes, re-runs (Scenario 1)

Setup: Capped budget ``C`` with ``T=$50``, ``A=$20``, ``B=$10``.
Today's fund event fires.  ``Unallocated`` has only ``$5``.

**3:00 AM engine run:**

- ``B_0 = 10 - 0 = 10`` (no system ITXs on today yet).
- ``intended = min(20, max(0, 50 - 10)) = min(20, 40) = 20``.
- ``already_moved = 0``.
- ``transfer = max(0, 20 - 0) = 20``, clamped by ``Unallocated`` = ``5``.
- Engine issues a system ITX: ``Unallocated -> C, $5,
  system_event_kind="F", system_event_date=today``.
- Pointer advances to today.
- Warning logged: "Capped C: fund event intended $20, only $5 available."

**11:00 AM, user moves $40 from another budget to ``Unallocated``.**

**11:05 AM, user clicks "Run funding now":**

The engine always processes today's events (section 9).

- ``B_0 = current B(=$15) - sum(signed_amount(C) for system ITX with system_event_date >= today)``
  ``= 15 - (+5) = $10``.
- ``intended = min(20, max(0, 50 - 10)) = 20``.
- ``already_moved = +$5`` (the 3 AM ITX, signed for ``C``).
- ``transfer = max(0, 20 - 5) = 15``, clamped by current ``Unallocated`` = $40, so $15.
- Engine issues a system ITX: ``Unallocated -> C, $15,
  system_event_kind="F", system_event_date=today``.
- Pointer remains at today.

Result: ``C.balance = $30``.  Total system transfers today: $20 = ``A``.
The user got the automatic top-up they expected, no double-counting,
no manual ITX needed.

**Tomorrow 3 AM:** Catch-up range ``(today, tomorrow)`` is empty.
Today (= tomorrow now) processes tomorrow's scheduled events only;
yesterday's now-fully-satisfied fund event is not revisited.

### 14.2 Recurring recur event shortfall, user moves money to fillup (Scenario 2)

Setup: Recurring budget ``R`` with ``T=$200``, ``B=$0``.  Fill-up
``F`` with ``Fill_B=$120``.  Today is the recurrence date.

**3:00 AM engine run, recur event:**

- ``B_0(R, today) = 0 - 0 = 0``; ``Fill_B_0(today) = 120 - 0 = 120``.
- ``intended = min(max(0, 200 - 0), 120) = 120``.
- ``already_moved = 0``.
- ``transfer = max(0, 120 - 0) = 120``, clamped by current ``Fill_B`` = $120.
- Engine issues a system ITX: ``F -> R, $120, system_event_kind="R",
  system_event_date=today``.
- Pointer advances to today.
- Post-transfer: ``R.balance = $120``, ``Fill_B = $0``.
- Warning logged: "Recurring R: recur event intended $200, only $120
  available in fill-up."

**10:00 AM, user moves $80 from other budgets into the fill-up via
a manual user ITX.**  After: ``Fill_B = $80``, ``R.balance = $120``.
The manual ITX is not system-issued (``actor`` is the user, not
``funding-system``), so it does not count toward ``already_moved``.

**10:05 AM, user clicks "Run funding now":**

The engine always processes today's events (section 9).  It re-runs
today's recur event:

- ``B_0(R, today) = current R.balance($120)`` ``- sum(signed_amount(R) for system ITX with system_event_date >= today)($120) = 0``.
- ``Fill_B_0(today) = current Fill_B($80)`` ``- sum(signed_amount(F) for system ITX with system_event_date >= today)($-120) = $200``.
- ``intended = min(max(0, 200 - 0), 200) = 200``.
- ``already_moved = +$120`` (the 3 AM ITX, signed for ``R``).
- ``transfer = max(0, 200 - 120) = 80``, clamped by current ``Fill_B`` = $80.
- Engine issues a system ITX: ``F -> R, $80, system_event_kind="R",
  system_event_date=today``.
- Pointer remains at today.

Post-transfer: ``R.balance = $200``, ``Fill_B = $0``.  The Recurring
is fully funded -- the user's intent in Scenario 2 is met.

**Tomorrow 3 AM:** Catch-up range ``(today, tomorrow)`` is empty.
Today (= tomorrow now) processes tomorrow's scheduled events only;
yesterday's recur is not revisited.  This is the intended behavior:
recur events live and die with their scheduled day.

**If the user had not topped up before midnight**, the Recurring
would have stayed at $120 for the cycle.  The warning at 3 AM is the
user's only signal that intervention is needed; tomorrow's engine
run will not retroactively try to fix the cycle.  Fund events fired
on subsequent days correctly accumulate into the fill-up for the
*next* cycle -- they do not bleed into closing the previous cycle's
shortfall.

### 14.3 Daemon misses Tuesday; Wednesday's 3am catches up

Setup: Goal ``G`` with ``T=$100``, ``F=$0``, ``funding_type=TARGET_DATE``,
funding_schedule fires every weekday, target_date = next Friday.
Monday pointer: last_funded_on = Sunday.

Tuesday 3am: server is rebooting; engine does not run.

Wednesday 3am engine run:

- Events in ``(Sunday, Wednesday]`` for ``G``: Monday, Tuesday,
  Wednesday.
- Process Monday: ``N_to_target`` counts events Mon, Tue, Wed, Thu,
  Fri = 5.  ``F_0 = 0 - 0 = 0``.  ``intended = (100 - 0) / 5 = 20``.
  Issue system ITX for Monday, ``$20``.  Pointer = Monday.
- Process Tuesday: ``F = 20``.  ``F_0 = 20 - 20 = 0``.  Wait, let me
  re-derive.  ``F_0(Tuesday) = current F - sum(system ITX with
  system_event_date >= Tuesday)``.  Current F = $20 (Monday's
  transfer).  System ITX with date >= Tuesday: none yet.  So
  ``F_0(Tuesday) = 20``.

  ``N_to_target`` from Tuesday through Friday = 4.
  ``intended = max(0, 100 - 20) / 4 = 20``.
  Issue system ITX for Tuesday, ``$20``.  Pointer = Tuesday.
- Process Wednesday: current F = $40.  System ITX with date >= Wed:
  none.  ``F_0(Wed) = 40``.  ``N_to_target = 3``.
  ``intended = 60 / 3 = 20``.  Issue Wednesday ITX, $20.  Pointer =
  Wednesday.

Three transfers, even spacing, no double-counting, target_date stays
hit.

### 14.4 Pause across recur boundary

Setup: Recurring ``R``, funding twice monthly (15th and last day),
recur on 1st of month.  Today = Jan 16; user pauses ``R``.  Three
months later (Apr 3) user unpauses.

On unpause, ``budget_svc.update`` (or equivalent):

- Sets ``R.paused = False``.
- Sets ``R.last_funded_on = Apr 2``.
- Sets ``R.last_recurrence_on = Apr 2``.
- Emits a warning per missed recur boundary (Feb 1, Mar 1, Apr 1):
  "Recurring R was paused across recur boundary YYYY-MM-01; cycle
  skipped."

These warnings surface on the budget-update API response as a
``warnings: list[str]`` field on ``BudgetSerializer``'s response
payload (analogous to ``FundingReport.warnings`` for engine runs).
They are also written to the application logger at ``WARNING`` level
so they appear in server logs / Sentry.

Apr 3 engine run: no events in ``(Apr 2, Apr 3]``.  No-op.

Apr 15 engine run (fund event):

- ``Fill_B_0 = whatever the fill-up has``.  Note that during the
  pause, the user could have manually moved money in or out of the
  fill-up; the engine doesn't care -- it computes from current state.
- ``N_in_cycle`` = number of fund events from Apr 15 through May 1:
  Apr 15, Apr 30 = 2.
- ``intended = max(0, T - Fill_B_0) / 2``.  Engine transfers
  accordingly.

This matches the user's stated scenario in the refinement
conversation.


## 15. Existing-test scenarios: preserved, changed, removed

| Test class (``app/tests/moneypools/test_funding.py``) | Status under new spec |
|---|---|
| ``TestFundingEngineSingleEvent``                  | **Preserved** (parameter values may shift) |
| ``TestFundingEngineRecurringWithFillup``          | **Preserved**; assertions on the per-event amount formula change |
| ``TestFundingEngineMultiPeriodCatchup``           | **Preserved**; the "intended" formula is now stateless-with-rollback (section 6) |
| ``TestImportFreshnessGate``                       | **Preserved** as-is |
| ``TestCapAndWarn``                                | **Changed**: empty / partial ``Unallocated`` is now treated as "event over" -- the pointer advances and the missed amount is lost on subsequent days.  The user gets a same-day re-run window via "today always processed," but next-day retries no longer happen.  Tests that assert next-day retry semantics must be rewritten. |
| ``TestGoalCompletion``                            | **Changed**: completion now driven by ``funded_amount`` and the latch in ``internal_transaction_svc.create``, not by ``balance``. |
| ``TestPausedAndArchived``                         | **Changed**: paused-budget pointer behavior moves out of the engine into the unpause service call. |
| ``TestIdempotency``                               | **Changed**: idempotency is now intended-amount based.  Same-day re-run with no state change is a no-op because ``already_moved == intended``; same-day re-run after a partial tops up.  Pointer-position no longer plays an idempotency role. |
| ``TestCeleryFanOut``                              | **Preserved** as-is |
| ``TestMarkImportedEndpoint``                      | **Preserved** as-is |
| ``TestNextFundingInfo``                           | **Preserved**; the calculation it surfaces just uses the new formulas |
| ``TestPreCycleCatchupFunding``                    | **Removed**: the "anchor to theoretical prior boundary" logic was specific to the old catch-up replay model.  New engine has nothing to anchor; events are by schedule, period. |
| ``TestFillAmountProrated``                        | **Preserved**; the formula is the same shape but it now reads ``Fill_B_0`` instead of current ``Fill_B``. |
| ``TestRecurringTargetDateProration``              | **Preserved** |

A new test class is added: ``TestSameDayRerun``, parameterized over
budget type and partial-vs-fresh scenarios.  Each parameter is a
``pytest.param(...)`` constructed per the scenario matrix at the end
of section 16.


## 16. Test scenario matrix

The test suite for the new funding engine is organized around a
parametrized scenario generator, one parametrized test per budget
type, where each parameter encodes a chain of events: budget setup,
day-by-day Unallocated balance, manual ITXs, pauses, and the expected
state after each engine run.

The scenarios to cover, per type:

**Goal**

1. Fully funded; later allocation drops balance; ``complete`` stays True.
2. Archived before complete.
3. Archived after complete.
4. Spending via allocation before complete (``funded_amount``
   unaffected; ``balance`` drops).
5. Manual ITX in before complete (``funded_amount`` rises; can
   trigger completion latch).
6. Manual ITX out before complete (``funded_amount`` drops;
   subsequent fund events make up the difference).
7. Manual ITX out after complete (``funded_amount`` drops below
   target; ``complete`` stays True; no future fund events).
8. Paused for one fund event; unpaused; pointer at unpause-day-minus-1;
   next event fires.
9. FIXED_AMOUNT: identical-amount transfers per event until target.
10. TARGET_DATE: per-event amount adjusts as ``F`` and ``N_to_target``
    change.

**Capped**

1. Fund up to cap; spend; refund up to cap on next event.
2. Spend below cap mid-event; same-day re-run picks up the difference.
3. Empty Unallocated on event day; user adds; same-day re-run completes.

**Recurring**

1. Empty Unallocated on fund event day; same-day re-run completes
   after user tops up.
2. Recur event with insufficient fill-up; same-day re-run after user
   moves money to fill-up completes the recur sweep.
3. Recur event with insufficient fill-up; user does NOT top up
   same-day; pointer advances; next day no retry.
4. Fund event amount adjusts each event as ``Fill_B`` and
   ``N_in_cycle`` change.
5. Multi-cycle: recur, spend, recur again, fill-up excess accumulates.
6. Pause across recur boundary; warning emitted at unpause; cycle
   lost.

These are implemented as ``pytest.parametrize`` parameters on a small
number of generic test functions, one per budget type.  Each parameter
is a list of ``(day, action)`` tuples that the test runner applies in
order, asserting state after each.
