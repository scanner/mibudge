# Importing Transactions and Backfilling Budgets

The `importers/` directory contains standalone CLI tools for getting data into mibudge. They authenticate with the mibudge REST API using a normal username and password -- they do not require direct access to the server, the database, or Django management commands. Anyone with a mibudge account can run them.

These tools will eventually live in their own repository. For now they share the project's `pyproject.toml` and are run from the repo root with `uv run`.

---

## Tools

| Tool | Command | Purpose |
|------|---------|---------|
| Statement importer | `python -m importers import` | Parse bank statement files (OFX/QFX or BofA CSV) and POST new transactions to mibudge |
| Budget backfill | `python -m importers backfill_budget` | Interactively allocate historical transactions to a budget, month by month |

---

## Setup

### Credentials

All tools accept connection and credential flags. In practice, set them once in a `.env` file at the repo root:

```bash
MIBUDGE_URL=https://your-mibudge-host
MIBUDGE_USERNAME=you@example.com
MIBUDGE_PASSWORD=yourpassword
```

Alternatively, pull credentials from HashiCorp Vault:

```bash
export VAULT_ADDR=https://vault.example.com
export VAULT_TOKEN=s.xxxx
uv run python -m importers --vault-path mibudge/prod import stmt.ofx
```

The Vault secret must have keys `url`, `username`, and `password`.

### Local dev with a self-signed cert

```bash
# Auto-detect mkcert root CA:
uv run python -m importers --trust-local-certs import stmt.ofx

# Or specify a CA bundle explicitly:
uv run python -m importers --ca-bundle "$(mkcert -CAROOT)/rootCA.pem" import stmt.ofx
```

---

## Statement Importer

Parses one or more bank statement files and imports their transactions into mibudge. Statements are validated for internal consistency before any API calls are made. Already-imported transactions are detected and skipped -- re-running the same file is safe.

### Supported formats

| Extension | Parser | Carries account identity? |
|-----------|--------|--------------------------|
| `.ofx`, `.qfx` | OFX/QFX | Yes -- `ACCTID` and account type from the file |
| `.csv` | Bank of America CSV | No -- account must be specified or created via flags |

### Routine import (OFX/QFX, account already exists)

For an existing account, the OFX `ACCTID` is matched against the account's stored account number automatically. This is the common case for monthly imports:

```bash
uv run python -m importers import ~/Downloads/*.ofx
```

Multiple files for the same account can be passed in one run. They are sorted by date and a warning is emitted if consecutive statements have a gap.

### First import from OFX/QFX (create the account)

The account type and number come from the OFX file; only the display name and parent bank are needed:

```bash
# List banks to find the UUID:
uv run python -m importers banks

uv run python -m importers import --create-account \
    --name "Personal Checking" \
    --bank <bank-uuid-or-name> \
    ~/Downloads/2025-*.ofx
```

### First import from BofA CSV (create the account)

CSV files carry no account identity, so all account details must be supplied:

```bash
uv run python -m importers import --create-account \
    --name "Joint Checking" \
    --bank <bank-uuid-or-name> \
    --account-type checking \
    --account-number 1234567890 \
    ~/Downloads/stmt.csv
```

### Routine import from BofA CSV (account already exists)

Since CSVs have no `ACCTID` to match on, the account must be identified explicitly:

```bash
uv run python -m importers import --account <account-uuid-or-name> \
    ~/Downloads/stmt.csv
```

### Dry run

Parse, validate, and check for duplicates without posting anything:

```bash
uv run python -m importers import --dry-run ~/Downloads/*.ofx
```

### Flag reference

| Flag                                       | Purpose                                                     |
|--------------------------------------------|-------------------------------------------------------------|
| positional paths or `-f, --file`           | Statement files (repeatable, shell globs accepted)          |
| `--account, -a`                            | Target account by UUID or name fragment                     |
| `--create-account`                         | Create the destination account before importing             |
| `--name`                                   | Account display name (create mode)                          |
| `--bank`                                   | Parent bank UUID or name (create mode)                      |
| `--account-type checking\|savings\|credit` | Account type (create mode, CSV only)                        |
| `--account-number`                         | Account number (create mode, CSV only)                      |
| `--dry-run, -n`                            | Validate and dedup-check without importing                  |
| `--run-funding`                            | Run the funding engine after a successful import            |
| `--verbose, -v`                            | Debug logging                                               |
| `--plain`                                  | Disable rich terminal output (auto-detected when not a TTY) |

### Running the funding engine after import

The importer does **not** trigger funding automatically. If you want to fund budgets immediately after importing, pass `--run-funding`:

```bash
uv run python -m importers import ~/Downloads/*.ofx --run-funding
```

This calls `POST /api/v1/bank-accounts/<id>/run-funding/` after the import completes and prints the result (number of transfers, any warnings, skipped budget names). The flag is silently ignored on `--dry-run` runs.

Without `--run-funding`, the funding engine will still run automatically at 3:00 AM each night.

### Account resolution

The importer resolves the destination account with this precedence:

1. `--account` flag (explicit, wins everything)
2. OFX `ACCTID` matched against existing account numbers (OFX/QFX only)
3. `--create-account` (creates a new account)

Ambiguous or conflicting combinations are rejected with a clear error.

### Pre-flight validation

Before any API calls, each statement is checked for internal consistency:

- **Running-balance walk** -- applying each transaction's amount must reproduce the reported running balances
- **Summary totals** (CSV only) -- `beginning + credits + debits == ending`
- **Cross-file gap detection** (multi-file runs) -- a gap between consecutive statements emits a warning but does not abort

A file that fails its own consistency check is rejected before touching the server.

---

## Pending Transactions

Banks often surface in-flight transactions (authorizations not yet settled) before they post. mibudge supports this natively: a transaction can be imported with `pending=True`, which affects `available_balance` immediately but not `posted_balance` until it settles.

The BofA live scraper is the current importer that produces pending transactions — BofA shows "Processing" in the date column for unsettled items. Any future importer that can distinguish pending from posted transactions can use the same mechanism.

### What you can and cannot do with pending transactions

- **Pending transactions are display-only.** They are imported with a single allocation to the account's Unallocated budget, and that allocation cannot be changed while the transaction is pending. Attempting to split a pending transaction is rejected.
- Once a pending transaction settles, it transitions to posted status and behaves like any other transaction — you can split it, allocate it, and so on.

### How pending transactions settle

Each time the live scraper runs, it performs a pending-resolution pass before importing new transactions. For every settled scraped transaction it looks for a matching pending row in mibudge — matching on identical `raw_description` and a `posted_date` within 5 calendar days. When a match is found, mibudge atomically:

1. Clears the `pending` flag
2. Updates `posted_date` to the settled date
3. Credits `posted_balance` by the final amount
4. If the final settled amount differs from the pending estimate, adjusts `available_balance` by the delta and updates the Unallocated allocation

The resolution pass runs before the normal dedup check, so settled rows do not appear as duplicate imports.

Pending resolution is also available directly via the REST API (`POST /api/v1/transactions/<id>/resolve-pending/`) for integrations that handle their own matching logic.

### Known limitation: stuck-pending rows

If a pending transaction never settles (cancelled authorization, returned charge, etc.) the row will remain pending in mibudge indefinitely. Each subsequent scrape that sees the same pending transaction will attempt to match it but find no settled counterpart, leaving it untouched. However, if the bank later shows the same description as a new settled transaction on a different date, the description-match heuristic may resolve it incorrectly. In that edge case, delete the stuck-pending row manually and let the next scrape import the settled version fresh.

---

## Budget Backfill

Interactively allocates historical transactions to a single budget, month by month. Use this when you've added a new budget and want to assign past transactions to it without doing it one-by-one in the UI.

```bash
uv run python -m importers backfill_budget \
    --account "Personal Checking" \
    --budget "Groceries"
```

The tool fetches all transactions for the account, groups them into monthly periods, and steps through each unallocated transaction asking whether it belongs to the budget. Vendor names are extracted from raw bank descriptions, and you can save yes/no rules per vendor so repeat merchants are handled automatically in future runs.

Transactions, allocations, and internal transactions are all fetched once at startup. Any transactions imported while the script is running will not appear in the current session — re-run after importing new transactions to pick them up.

### Prompts

| Key | Action                                                           |
|-----|------------------------------------------------------------------|
| `y` | Allocate this transaction to the budget                          |
| `n` | Skip this transaction                                            |
| `a` | Always allocate this vendor to this budget (saves rule)          |
| `s` | Skip all remaining transactions from this vendor in this session |
| `q` | Quit and save rules                                              |

Saved rules are stored in `~/.mibudge/vendor_rules.json` keyed by budget UUID.

### Funding between periods

At the end of each monthly period, the tool automatically funds the budget to prepare it for the next period:

- **Recurring budget** -- tops up to `target_balance`
- **Capped budget** -- adds `funding_amount`, up to the cap ceiling

### Re-running the backfill

Re-running the script for a budget you have already backfilled is safe. Before processing begins, the tool fetches all existing funding transfers (Unallocated → target budget InternalTransactions) and records their effective dates in a `funded_dates` set. Any period whose funding date is already in that set is silently skipped -- no duplicate transfer is created. Only transactions that are still allocated to Unallocated are shown for review; anything already allocated to another budget is ignored.

If reassigning transactions causes the budget's balance to go negative (because spending now exceeds the funding that was originally recorded), that is not corrected automatically. You are responsible for making a manual internal transfer to bring the budget back to zero or above.

### Flag reference

| Flag            | Purpose                                  |
|-----------------|------------------------------------------|
| `--account, -a` | Bank account by UUID or name (required)  |
| `--budget, -b`  | Target budget by UUID or name (required) |
| `--verbose, -v` | Debug logging                            |
| `--plain`       | Disable rich terminal output             |

---

## Developer notes

Full developer documentation -- parser internals, adding new bank formats, multi-file dedup semantics, OFX balance derivation edge cases -- is in [`importers/README.md`](../importers/README.md).

To run the importer test suite:

```bash
uv run pytest importers/tests/ -v
```
