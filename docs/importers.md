# Importing Transactions and Backfilling Budgets

The `importers/` directory contains standalone CLI tools for getting data into mibudge. They authenticate with the mibudge REST API using an API key (preferred; create one under Settings -> API keys, pass it via `--api-key` / `MIBUDGE_API_KEY`) or a normal email and password -- they do not require direct access to the server, the database, or Django management commands. Anyone with a mibudge account can run them.

These tools will eventually live in their own repository. For now they share the project's `pyproject.toml` and are run from the repo root with `uv run`.

---

## Tools

| Tool | Command | Purpose |
|------|---------|---------|
| Statement importer | `python -m importers import` | Parse bank statement files (OFX/QFX or BofA CSV) and POST new transactions to mibudge |
| BofA live scraper | `python -m importers.import_bofa_live` | Log in to Bank of America, scrape all accessible accounts, and sync each one into mibudge via the `sync-scrape` endpoint |
| BofA saved-scrape replayer | `python -m importers.import_bofa_saved` | Replay saved BofA scrape JSON files through the same `sync-scrape` endpoint without re-logging in to BofA |
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

### Environment variables for every flag

Every flag on every command has a corresponding environment variable. All importers use `MIBUDGE_` as the prefix; click derives the variable name automatically: `--flag-name` → `MIBUDGE_FLAG_NAME` (uppercase, hyphens replaced with underscores). For example:

| Flag | Environment variable |
|------|----------------------|
| `--url` | `MIBUDGE_URL` |
| `--username` | `MIBUDGE_USERNAME` |
| `--dry-run` | `MIBUDGE_DRY_RUN` |
| `--run-funding` | `MIBUDGE_RUN_FUNDING` |
| `--save-dir` | `MIBUDGE_SAVE_DIR` |
| `--verbose` | `MIBUDGE_VERBOSE` |

Two flags on the BofA live scraper use explicit names that override the auto-prefix: `--bofa-id` reads `BOFA_ID` and `--bofa-passcode` reads `BOFA_PASSCODE` (not `MIBUDGE_BOFA_ID` / `MIBUDGE_BOFA_PASSCODE`).

CLI flags always take precedence over environment variables.

Alternatively, pull credentials from HashiCorp Vault:

```bash
export VAULT_ADDR=https://vault.example.com
export VAULT_TOKEN=s.xxxx
uv run python -m importers --vault-path mibudge/prod import stmt.ofx
```

The Vault secret must have `url` plus either `api_key` (preferred) or `email` and `password`.

Or pull just the API key from 1Password (set `--api-key-onepassword-url` / `MIBUDGE_API_KEY_ONEPASSWORD_URL` to a full secret reference -- `op://<vault>/<item>[/<section>]/<field>`, e.g. `op://Personal/mibudge/API key` -- naming the field that holds the key used to authenticate to mibudge; requires the `op` CLI signed in). Since the reference names the field, one item can hold several API keys under different section/field names. This is a distinct env var from the BofA scraper's own `BOFA_ONEPASSWORD_URL` -- see [BofA Live Scraper](#bofa-live-scraper) below.

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

Every flag can also be set via its `MIBUDGE_FLAG_NAME` environment variable (see [Environment variables for every flag](#environment-variables-for-every-flag)).

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

## BofA Live Scraper

The live scraper logs into Bank of America using a Selenium/Firefox driver and syncs all accessible accounts into mibudge.

### Installation

The scraper requires an optional dependency group:

```bash
uv sync --group importers-bofa
```

### Usage

```bash
uv run --group importers-bofa python -m importers.import_bofa_live
```

BofA credentials are read from `BOFA_ID` and `BOFA_PASSCODE` environment variables (or `--bofa-id` / `--bofa-passcode` flags), or from a 1Password item via `--bofa-onepassword-url` / `BOFA_ONEPASSWORD_URL` (reads the item's `username`/`password` fields). mibudge credentials use the same resolution order as the statement importer (CLI flags → env vars → `.env` → the mibudge 1Password secret reference via `--api-key-onepassword-url` / `MIBUDGE_API_KEY_ONEPASSWORD_URL` → Vault). The two 1Password URLs are separate env vars on purpose -- each name says which credential it fetches -- and they differ in shape: the BofA one is an *item* URL (its `username`/`password` fields are both read), while the mibudge one is a full secret reference naming the field that holds the API key.

If BofA requires 2FA, the scraper prompts for the code interactively via stdin. Run with `--no-headless` to watch the browser.

### Transaction details enrichment

For posted transactions BofA can serve a per-transaction detail record (merchant name, "CITY, ST" location, category, ISO 18245 MCC, masked virtual card number). After each account's `sync-scrape` POST, the server reports `details_needed` -- the rows whose DB transaction has never been enriched -- and the importer fetches those details while the scrape session is still open, then POSTs them to the `transaction-details` endpoint. The importer translates BofA's category string into a mibudge category full name (see Category mapping below) and submits it with each item; the server stores the raw dict, extracts the merchant columns, seeds the transaction's category (and its unassigned splits) when unassigned, and recomposes the display description ("Trader Joes -- Menlo Park, CA (Grocery Stores and Supermarkets)") unless the user has edited it.

Two things keep this under BofA's rate limit (a burst of ~40-50 detail-dialog opens wedges the page and can kill the login session):

- **A run-wide fetch budget.** `--details-limit` (default 30) counts dialog opens across all accounts in the run, paced with empirically tuned delays and wedge recovery. Rows left over stay unenriched server-side and are re-reported by the next sync, so a backfill converges over successive runs. `--details-limit 0` disables detail fetching.
- **Merchant-copy.** BofA's details are stable per merchant, so each merchant is fetched only once per run; the merchant's other rows get a synthesized copy at zero dialog cost (provenance-marked `details_source: merchant-copy`, and without the per-transaction `virtual_card_number`). In practice a backfill costs one fetch per *merchant*, not per transaction.

### Saving scrape output

Pass `--save-dir <dir>` to write each account's raw scraped data to a JSON file (`YYYY-MM-DD-HHMMSS-<last4>.json`, format v3 -- fetched transaction details are included). This lets you re-import from the saved file later without re-logging in to BofA. Combine with `--save-only` to capture the data on a machine that can reach BofA but not mibudge; add `--details-all` to force-capture the real detail dialog for every posted transaction (paced, no merchant-copy shortcut) so the file carries the full data:

```bash
# Capture on BofA-accessible machine:
uv run --group importers-bofa python -m importers.import_bofa_live \
    --save-dir ./saved --save-only --details-all

# Replay later (also replays any saved details):
uv run python -m importers.import_bofa_saved saved/*.json
```

### Flag reference

Every flag can also be set via its `MIBUDGE_FLAG_NAME` environment variable (see [Environment variables for every flag](#environment-variables-for-every-flag)). The two exceptions are noted below.

| Flag | Purpose |
|------|---------|
| `--bofa-id` | BofA Online ID (env var: `BOFA_ID`, not `MIBUDGE_BOFA_ID`) |
| `--bofa-passcode` | BofA passcode (env var: `BOFA_PASSCODE`, not `MIBUDGE_BOFA_PASSCODE`) |
| `--bofa-onepassword-url` | 1Password item URL for BofA username/password (env var: `BOFA_ONEPASSWORD_URL`, not `MIBUDGE_BOFA_ONEPASSWORD_URL`) |
| `--api-key-onepassword-url` | 1Password secret reference (full field path) to the API key used to authenticate to mibudge (env var: `MIBUDGE_API_KEY_ONEPASSWORD_URL`) |
| `--account, -a` | Filter by BofA account name substring (repeatable; omit for all accounts) |
| `--headless / --no-headless` | Run Firefox headlessly (default) or visibly for debugging/2FA |
| `--timeout` | Selenium page-load timeout in seconds (default: 5) |
| `--save-dir` | Directory to write raw scrape JSON files |
| `--save-only` | Scrape and save without importing; requires `--save-dir` |
| `--details-limit` | Max detail-dialog opens per run across all accounts (default: 30; 0 disables detail fetching) |
| `--details-all` | With `--save-only`: capture the real detail dialog for every posted transaction, ignoring `--details-limit` |
| `--dry-run, -n` | Show what would be synced without making any changes |
| `--run-funding` | Run the funding engine after each successful account sync |
| `--verbose, -v` | Debug logging |
| `--plain` | Disable rich terminal output |

---

## BofA Category Mapping

Translating BofA's category vocabulary (`Groceries : Groceries`,
`Shopping & Entertainment : Electronics`, ...) into mibudge categories
is the **importer's job** -- mibudge only understands its own category
full names (`"{group} : {name}"`), submitted with each
transaction-details item. See
[transaction-categories.md](transaction-categories.md) for the model
side.

Three layers, all in `importers/bofa_categories.py`:

- **`BOFA_CATEGORY_MAP`** -- the built-in reviewed mapping, covering
  every category string BofA has been observed to use. A `null` target
  means "deliberately leave the transaction unassigned" (the user
  categorizes it).
- **Overlay map** -- `--category-map FILE` (env var
  `MIBUDGE_CATEGORY_MAP`) on both the live scraper and the saved-scrape
  replayer loads a flat YAML mapping that merges over the built-ins.
  This is how a newly discovered BofA category gets mapped without a
  code release:

  ```yaml
  # bofa-category-overlay.yaml
  'some new bofa group:its name': 'Food & Drink : Groceries'
  'another one:thing': null   # leave unassigned on purpose
  ```

  Keys are normalized provider strings (split on the first colon,
  whitespace collapsed, casefolded); values are mibudge category full
  names or `null`.
- **End-of-run report** -- any BofA category found in neither map is
  listed at the end of the run (its transactions land unassigned).
  Add those keys to the overlay, or extend `BOFA_CATEGORY_MAP` and
  open a PR -- a unit test verifies every built-in target names a
  seeded canonical category.

## Pending Transactions

Banks often surface in-flight transactions (authorizations not yet settled) before they post. mibudge supports this natively: a transaction can be imported with `pending=True`, which affects `available_balance` immediately but not `posted_balance` until it settles.

The BofA live scraper is the current importer that produces pending transactions -- BofA shows "Processing" in the date column for unsettled items. Any future importer that can distinguish pending from posted transactions can use the same mechanism.

### What you can and cannot do with pending transactions

- **Pending transactions are display-only.** They are imported with a single allocation to the account's Unallocated budget, and that allocation cannot be changed while the transaction is pending. Attempting to split a pending transaction is rejected.
- Once a pending transaction settles, it transitions to posted status and behaves like any other transaction -- you can split it, allocate it, and so on.

### How the scrapers handle pending transactions

The BofA live and saved scrapers use the `sync-scrape` endpoint (`POST /api/v1/bank-accounts/<id>/sync-scrape/`). On every run, the scraper hands the server the full current bank-side snapshot -- posted and pending transactions together. The server reconciles atomically:

1. **Wipe pending**: all existing pending rows for the account are deleted (along with their Unallocated allocations).
2. **Dedup posted**: new settled transactions are compared against existing posted rows by (date, amount, raw description). Already-known rows are skipped; genuinely new ones are inserted.
3. **Re-insert pending**: the scraper's current pending list is inserted fresh.
4. **Snapshots recomputed**: per-transaction running balance snapshots and the Unallocated budget allocation snapshots are updated before the response returns.

This approach means pending transaction UUIDs are not stable across scrapes -- the DB record is deleted and re-created on every sync. Any external reference to a pending transaction's UUID will be stale after the next run.

Cancelled authorizations and "stuck" pending rows are cleaned up automatically: if the bank stops showing a pending transaction, the next sync removes it with no manual intervention.

**Description normalization**: BofA appends "Amount may change - waiting for final amount from merchant" (via a `<br>` tag, rendered as a newline by the scraper) to some pending descriptions for restaurant-style transactions where the final charge may differ from the authorization. The scraper strips everything from the first newline onward so that raw descriptions are clean and consistent regardless of pending/settled status.

### Manual pending resolution

The `resolve-pending` REST API (`POST /api/v1/transactions/<id>/resolve-pending/`) is available for integrations or importers that handle their own matching logic and need to transition an individual pending row to posted status.

---

## Budget Backfill

Interactively allocates historical transactions to a single budget, month by month. Use this when you've added a new budget and want to assign past transactions to it without doing it one-by-one in the UI.

```bash
uv run python -m importers backfill_budget \
    --account "Personal Checking" \
    --budget "Groceries"
```

The tool fetches all transactions for the account, groups them into monthly periods, and steps through each unallocated transaction asking whether it belongs to the budget. Vendor names are extracted from raw bank descriptions, and you can save yes/no rules per vendor so repeat merchants are handled automatically in future runs.

Transactions, allocations, and internal transactions are all fetched once at startup. Any transactions imported while the script is running will not appear in the current session -- re-run after importing new transactions to pick them up.

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

Every flag can also be set via its `MIBUDGE_FLAG_NAME` environment variable (see [Environment variables for every flag](#environment-variables-for-every-flag)).

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
