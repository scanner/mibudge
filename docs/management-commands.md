# Management Commands

Django management commands for operating and maintaining mibudge. All commands run via:

```bash
uv run python app/manage.py <command> [options]
```

Or inside the Docker container:

```bash
make shell
python manage.py <command> [options]
```

These commands require direct access to the Django application -- they are not exposed through the REST API. Most are relevant only when the person administering the server is also a user of the service (self-hosted deployments). In a multi-tenant or managed deployment, end-user data flows exclusively through the REST API and the mobile/web clients.

---

## Quick reference

| Command                      | Purpose                                           | Category           |
|------------------------------|---------------------------------------------------|--------------------|
| `verify_balances`            | Audit the budget-vs-account balance invariant     | Service integrity  |
| `fund_budgets`               | Manually run the budget funding engine            | Service operations |
| `relink_transactions`        | Re-run the cross-account transaction linker       | Service operations |
| `export_bank_account`        | Dump an account to a JSON backup                  | Data management    |
| `import_bank_account`        | Restore an account from a JSON backup             | Data management    |
| `backfill_transaction_dates` | Re-derive purchase dates embedded in descriptions | Data management    |
| `recompute_running_balances` | Recalculate allocation balance snapshots          | Data management    |
| `define_budgets`             | Create or update budgets from a YAML file         | Budget setup       |
| `extract_budgets`            | Export budget definitions to YAML                 | Budget setup       |
| `clear_budget`               | Zero out a budget (dev and correction only)       | Data correction    |

---

## Service integrity

### verify_balances

Audits the core invariant: for every BankAccount, the sum of all budget balances must equal `posted_balance`. Read-only -- never mutates anything. Run this after any bulk operation or import to confirm the invariant holds.

```bash
uv run python app/manage.py verify_balances
uv run python app/manage.py verify_balances --account <UUID>
```

Exit code is non-zero on any failure, making it scriptable as a post-import check. Output includes a per-budget breakdown for any failing account.

| Option                | Description                                      |
|-----------------------|--------------------------------------------------|
| `--account UUID`      | Check only this bank account                     |
| `--tolerance DECIMAL` | Acceptable absolute difference (default: `0.00`) |

---

## Service operations

These commands are normally automated (Celery beat, post-import signals), but can be triggered manually for backfill, testing, or recovery.

### fund_budgets

Runs the budget funding engine for one or all accounts. Collects due funding and recurrence events since the last run and moves money between budgets via internal transactions. Safe to re-run -- already-processed events are skipped.

```bash
uv run python app/manage.py fund_budgets
uv run python app/manage.py fund_budgets --account "Checking"
uv run python app/manage.py fund_budgets --date 2026-04-01 --dry-run
```

Normally runs on a schedule via Celery Beat and is also triggered automatically when new transactions are imported via the REST API. Use this command for manual backfill or when replaying a date range.

| Option | Description |
|--------|-------------|
| `--account PATTERN` | Restrict to an account matching this name fragment or UUID prefix |
| `--date YYYY-MM-DD` | Override "today" for backfill or testing (default: current UTC date) |
| `--dry-run` | Show what would be funded without making any transfers |

### relink_transactions

Re-runs the opportunistic cross-account transaction linker over all unlinked transactions. Normally linking happens automatically via a post-save signal; this command handles stragglers after bulk imports or after updating the linking heuristic.

```bash
uv run python app/manage.py relink_transactions
uv run python app/manage.py relink_transactions --account <UUID>
```

Read-only with respect to balances -- only the `linked_transaction` FK on Transaction is touched. Idempotent; already-linked transactions are skipped.

| Option | Description |
|--------|-------------|
| `--account UUID` | Only consider transactions in this bank account as the driving side |

---

## Data management

These commands are primarily useful in self-hosted deployments where the person administering the server also manages their own account data: initial setup, backup/restore, and data correction after imports.

### export_bank_account

Dumps all data for a bank account to a portable JSON file: the Bank, BankAccount, all Budgets, Transactions with their allocations, and InternalTransactions.

```bash
uv run python app/manage.py export_bank_account --account "Checking" --output backup.json
uv run python app/manage.py export_bank_account --account "Checking"   # stdout
```

| Option | Description |
|--------|-------------|
| `--account PATTERN` | Account name fragment or UUID prefix (required) |
| `--output FILE` | Destination path; defaults to stdout |

The export is valid input for `import_bank_account`.

### import_bank_account

Restores a bank account from a JSON export. Recreates all rows with their original UUIDs. Idempotent -- re-running the same file updates existing rows rather than duplicating them.

```bash
uv run python app/manage.py import_bank_account backup.json --dry-run
uv run python app/manage.py import_bank_account backup.json
```

After importing, always run `verify_balances`. If importing multiple linked accounts (e.g. checking and its credit card), import all accounts first, then relink:

```bash
uv run python app/manage.py import_bank_account checking.json
uv run python app/manage.py import_bank_account credit-card.json
uv run python app/manage.py relink_transactions
uv run python app/manage.py verify_balances
```

| Option | Description |
|--------|-------------|
| `FILE` | Path to the JSON export file (required) |
| `--dry-run` | Parse and validate without writing to the database |

Dry-run validates the JSON structure and version, warns about missing owners and actors, but does not write anything.

### backfill_transaction_dates

Re-derives `transaction_date` for existing Transaction rows. In normal mode, only processes rows where `transaction_date == posted_date` (unenriched state). In `--force` mode, reprocesses all rows and re-anchors dates to midnight in the account owner's configured timezone.

```bash
uv run python app/manage.py backfill_transaction_dates
uv run python app/manage.py backfill_transaction_dates --account <UUID> --force
```

Use `--force` after a user sets or corrects their timezone, or after any run that stored dates as midnight UTC instead of midnight local time. Safe to re-run in normal mode -- only unenriched rows are touched.

| Option | Description |
|--------|-------------|
| `--account UUID` | Restrict to a single bank account |
| `--dry-run` | Print what would change without writing |
| `--force` | Reprocess all transactions and re-anchor to owner's timezone |

### recompute_running_balances

Recalculates all `TransactionAllocation.budget_balance` snapshots from scratch. Normally these are maintained incrementally by signals; use this after a bulk import or after deploying a bug fix that affected balance snapshot logic.

```bash
uv run python app/manage.py recompute_running_balances
uv run python app/manage.py recompute_running_balances --account "Checking"
uv run python app/manage.py recompute_running_balances --budget "Groceries"
```

Safe to re-run. Skips budgets with no allocations. Run `verify_balances` after to confirm.

| Option | Description |
|--------|-------------|
| `--account PATTERN` | Restrict to budgets in this account |
| `--budget PATTERN` | Restrict to a single budget by name fragment or UUID prefix |

---

## Budget setup

These commands support a file-based workflow for defining and updating budgets -- useful during initial account setup or when making bulk changes to budget definitions. Most day-to-day budget management goes through the REST API.

### define_budgets

Creates or updates budgets from a YAML definition file. Idempotent when budget entries include an explicit `id` -- existing budgets are updated in-place, new budgets are created.

```bash
uv run python app/manage.py define_budgets budgets.yaml --dry-run
uv run python app/manage.py define_budgets budgets.yaml
```

Dry-run shows each budget's action (CREATE or UPDATE) and the next 3 scheduled occurrences for each RRULE. All changes apply in a single atomic transaction.

**YAML format:**

```yaml
bank_account: "Scanner's Checking"

budgets:
  - name: Emergency Fund
    id: "7c4f9a2b-..."        # omit to auto-generate (loses idempotency)
    type: goal                 # goal | recurring | capped
    funding_type: target_date  # target_date | fixed_amount
    target_balance: "5000.00"
    target_date: 2026-12-31
    funding_schedule: "RRULE:FREQ=MONTHLY;BYMONTHDAY=1"
    memo: "3-month emergency fund"

  - name: Groceries
    id: "a1b2c3d4-..."
    type: recurring
    funding_type: fixed_amount
    target_balance: "400.00"
    funding_amount: "400.00"
    funding_schedule: "RRULE:FREQ=MONTHLY;BYMONTHDAY=1"
    recurrance_schedule: "RRULE:FREQ=MONTHLY;BYMONTHDAY=1"
    with_fillup_goal: true
```

| Field | Required | Description |
|-------|----------|-------------|
| `id` | Recommended | UUID for idempotency; auto-generated if omitted |
| `name` | Yes | Display name |
| `type` | Yes | `goal`, `recurring`, or `capped` |
| `funding_type` | Yes | `target_date` or `fixed_amount` |
| `target_balance` | Yes | Quoted decimal string |
| `funding_amount` | For `fixed_amount` | Amount credited per schedule event |
| `target_date` | For `goal` + `target_date` | ISO date |
| `funding_schedule` | Recommended | RFC 5545 RRULE string |
| `recurrance_schedule` | For `recurring` | RRULE string for cycle reset |
| `with_fillup_goal` | Optional | `true` to auto-create fill-up goal child |
| `paused` | Optional | `true` to pause automatic funding |
| `memo` | Optional | Free-text note |

| Option | Description |
|--------|-------------|
| `FILE` | Path to the YAML definition file (required) |
| `--dry-run` | Preview without writing |

### extract_budgets

Exports budget definitions to a YAML file suitable for `define_budgets`. Associated fill-up goal budgets and the unallocated budget are always omitted -- both are auto-managed.

```bash
# From the live database
uv run python app/manage.py extract_budgets "Scanner's Checking" -o budgets.yaml

# From a JSON export (no running DB needed)
uv run python app/manage.py extract_budgets --from-json backup.json -o budgets.yaml

# Single budget
uv run python app/manage.py extract_budgets "Scanner's Checking" --budget "Groceries"
```

Round-trip check: `extract_budgets ACCOUNT -o check.yaml && define_budgets check.yaml --dry-run` should show all UPDATEs with no functional changes.

| Option | Description |
|--------|-------------|
| `ACCOUNT` | Bank account name fragment or UUID (live DB) |
| `--from-json FILE` | JSON export from `export_bank_account` |
| `--budget PATTERN` | Extract a single budget by name or UUID |
| `--output FILE`, `-o` | Write to file instead of stdout |
| `--include-archived` | Include archived budgets (excluded by default) |

---

## Data correction

### clear_budget

Zeros out a budget by reassigning all its transaction allocations to the unallocated budget and reversing all its internal transactions. **Default behavior is dry-run** -- pass `--execute` to commit.

Intended for development and data correction only. The correct end-user path to retire a budget is to archive it (which preserves history). Use `clear_budget` when a budget was set up incorrectly and needs to be reset cleanly.

```bash
# Preview
uv run python app/manage.py clear_budget --budget "Groceries"

# Execute
uv run python app/manage.py clear_budget --budget "Groceries" --execute

# Execute and delete the budget row
uv run python app/manage.py clear_budget --budget "Groceries" --execute --delete
```

When run with a TTY, prompts for confirmation before executing.

| Option | Description |
|--------|-------------|
| `--budget PATTERN` | Budget name fragment or UUID prefix (required) |
| `--account PATTERN` | Restrict budget search to this account |
| `--execute` | Actually perform the operation (default is dry-run) |
| `--delete` | Also delete the budget row after clearing |
