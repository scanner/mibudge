# Importing Transactions and Backfilling Budgets

The `importers/` directory contains standalone CLI tools for getting data into mibudge. They authenticate with the mibudge REST API using an API key (preferred; create one under Settings -> API keys, and keep it in 1Password or HashiCorp Vault) or a normal email and password -- they do not require direct access to the server, the database, or Django management commands. Anyone with a mibudge account can run them.

These tools will eventually live in their own repository. For now they share the project's `pyproject.toml`, which declares each one as a console script.

### Where they are and how to run them

The importers install nothing outside the checkout. `uv sync` (or `make uv-sync`) installs the project into the checkout's `.venv`, and with it four commands in `.venv/bin/`:

| Command | Tool |
|---------|------|
| `mibudge-import` | Statement importer |
| `mibudge-bofa-live` | BofA live scraper |
| `mibudge-bofa-saved` | BofA saved-scrape replayer |
| `mibudge-backfill-budget` | Budget backfill |

Run them with `uv run` from anywhere in the checkout, with `uv run --project <checkout>` from elsewhere, or by their full path, `<checkout>/.venv/bin/mibudge-import`. `--help` on each lists every flag.

Wherever they are run from, they read the `.env` at the root of the checkout (the same file `make env` creates for the dev stack), never one in the current directory. They also read and write these files:

| File | Used by |
|------|---------|
| `<checkout>/.env` | every tool: `MIBUDGE_*`, `BOFA_*` and `VAULT_*` settings (never secrets) |
| `$XDG_CONFIG_HOME/mibudge-importers/config.toml` (default `~/.config/...`) | every tool: option values; see [Config file](#config-file) |
| `$XDG_CONFIG_HOME/mibudge-importers/bofa-accounts.json` | BofA live scraper: writes its cache of account nickname to last 4 digits |
| `$XDG_CONFIG_HOME/mibudge-importers/backfill-vendor-rules.json` | budget backfill: saved per-vendor yes/no rules |
| `--save-dir` / `MIBUDGE_SAVE_DIR` | BofA live scraper: writes raw scrape JSON when set |

The `mibudge-importers` directory holds no secrets and is meant to be synced between machines.

---

## Tools

| Tool | Command | Purpose |
|------|---------|---------|
| Statement importer | `mibudge-import` | Parse bank statement files (OFX/QFX or BofA CSV) and POST new transactions to mibudge |
| BofA live scraper | `mibudge-bofa-live` | Log in to Bank of America, scrape each account a mibudge account tracks, and sync it into mibudge via the `sync-scrape` endpoint |
| BofA saved-scrape replayer | `mibudge-bofa-saved` | Replay saved BofA scrape JSON files through the same `sync-scrape` endpoint without re-logging in to BofA |
| Budget backfill | `mibudge-backfill-budget` | Interactively allocate historical transactions to a budget, month by month |

---

## Setup

### Credentials

Every tool reaches mibudge with the same options:

| Flag | Environment variable | Purpose |
|------|----------------------|---------|
| `--url, -u` | `MIBUDGE_URL` | Base URL of the mibudge API (default `https://localhost:8000`) |
| `--mibudge-creds-url` | `MIBUDGE_CREDS_URL` | [Secret store](#secret-stores) holding the mibudge credentials |
| `--api-key` | none | mibudge API key |
| `--email` | `MIBUDGE_EMAIL` | Login email, for password login |
| `--password` | none | Login password |
| `--ca-bundle` | `MIBUDGE_CA_BUNDLE` | PEM CA bundle to trust instead of the system CAs |
| `--trust-local-certs` | `MIBUDGE_TRUST_LOCAL_CERTS` | Trust the mkcert root CA |

An API key wins over email and password. `--api-key` or `--password` is used as given; with neither, the store `--mibudge-creds-url` names is read for its `api_key` field, then for its `password` field (used with `--email`).

In practice, set the non-secret options once in the [config file](#config-file) and keep the API key in a secret store:

```toml
url = "https://your-mibudge-host"
mibudge_creds_url = "op://Personal/mibudge"
```

Secrets -- the API key (`MIBUDGE_API_KEY`), the password (`MIBUDGE_PASSWORD`) and the BofA passcode (`BOFA_PASSCODE`) -- are never read from the environment, `.env` or the config file, and a warning names any that are set in the environment or `.env`. Pass them as flags, or keep them in a secret store. `VAULT_TOKEN` is honored from the real environment but not from `.env`.

### Secret stores

A secret store is one record, named by a URL whose scheme picks the backend. The tools only read from it.

| URL | Backend |
|-----|---------|
| `op://<vault>/<item>` | A 1Password item |
| `hcvault://<host>/<mount>/<path>` | A secret in a HashiCorp Vault KV version 2 engine |

The URL names the record, not a field; each tool reads the fields it needs by name:

| Option | Fields read |
|--------|-------------|
| `--mibudge-creds-url` | `api_key`, else `password` |
| `--bofa-creds-url` (BofA live scraper) | `username` and `password` |

**1Password.** The tools run the `op` command line tool, which must be installed and signed in. A field is found by its label in any section of the item, so `op://Personal/mibudge` with a field labelled `api_key` is enough. Set `MIBUDGE_OP_BIN` when `op` is not on the `PATH`, or when more than one is and only a particular one can reach the account.

**HashiCorp Vault.** The first path segment is the KV engine's mount point and the rest is the secret's path under it, so `hcvault://vault.example.com:8200/secret/mibudge` reads `secret/data/mibudge`. A host in the URL is reached over https; leave it out (`hcvault:///secret/mibudge`) to use `VAULT_ADDR`. The Vault token comes from `VAULT_TOKEN`, then the `~/.vault-token` file `vault login` writes, and `VAULT_CACERT` names a CA bundle for a server whose certificate is not publicly trusted.

### Config file

Every tool reads option values from `config.toml` in the importers' config directory, `$XDG_CONFIG_HOME/mibudge-importers/` (default `~/.config/mibudge-importers/config.toml`), when it exists. `--config` / `MIBUDGE_CONFIG` names a different file, which must exist. A value is resolved in this order, first wins: CLI flag, environment variable (or `.env`), config file, the option's built-in default.

Keys are option names, spelled like the flag with or without its dashes (`save-dir` or `save_dir`). A top-level key applies to every tool that has that option and is ignored by the rest. A table named for a tool holds keys for that tool alone and wins over the top level:

| Table | Tool |
|-------|------|
| `[statements]` | `mibudge-import` |
| `[bofa_live]` | `mibudge-bofa-live` |
| `[bofa_saved]` | `mibudge-bofa-saved` |
| `[backfill_budget]` | `mibudge-backfill-budget` |

```toml
url = "https://mibudge.example.com"
email = "me@example.com"
mibudge_creds_url = "op://Personal/mibudge"
category_map = "categories.yaml"

[bofa_live]
bofa_creds_url = "op://Personal/BofA"
save_dir = "~/bofa-scrapes"
```

Relative paths resolve against the config file's directory, and `~` is expanded. A key that is no tool's option, a key in a table that is not that tool's option, and an unknown table are errors, whichever tool runs. Secrets (`password`, `api_key`, `bofa_passcode`) are refused because the directory is meant to be synced between machines: name a secret store instead.

### Environment variables for every flag

Every flag on every command has a corresponding environment variable. All importers use `MIBUDGE_` as the prefix; click derives the variable name automatically: `--flag-name` → `MIBUDGE_FLAG_NAME` (uppercase, hyphens replaced with underscores). For example:

| Flag | Environment variable |
|------|----------------------|
| `--url` | `MIBUDGE_URL` |
| `--email` | `MIBUDGE_EMAIL` |
| `--dry-run` | `MIBUDGE_DRY_RUN` |
| `--run-funding` | `MIBUDGE_RUN_FUNDING` |
| `--save-dir` | `MIBUDGE_SAVE_DIR` |
| `--verbose` | `MIBUDGE_VERBOSE` |

The secret flags (`--api-key`, `--password`, `--bofa-passcode`) have no environment variable. Three flags use explicit names that override the auto-prefix: `--mibudge-creds-url` reads `MIBUDGE_CREDS_URL`, and the BofA live scraper's `--bofa-id` and `--bofa-creds-url` read `BOFA_ID` and `BOFA_CREDS_URL`.

CLI flags always take precedence over environment variables.

### Local dev with a self-signed cert

```bash
# Auto-detect mkcert root CA:
uv run mibudge-import --trust-local-certs stmt.ofx

# Or specify a CA bundle explicitly:
uv run mibudge-import --ca-bundle "$(mkcert -CAROOT)/rootCA.pem" stmt.ofx
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
uv run mibudge-import ~/Downloads/*.ofx
```

Multiple files for the same account can be passed in one run. They are sorted by date and a warning is emitted if consecutive statements have a gap.

### First import from OFX/QFX (create the account)

The account type and number come from the OFX file; only the display name and parent bank are needed:

```bash
uv run mibudge-import --create-account \
    --name "Personal Checking" \
    --bank "Bank of America" \
    ~/Downloads/2025-*.ofx
```

`--bank` takes a bank's name, UUID or routing number. When it does not match exactly one bank, the importer lists the candidates.

### First import from BofA CSV (create the account)

CSV files carry no account identity, so all account details must be supplied:

```bash
uv run mibudge-import --create-account \
    --name "Joint Checking" \
    --bank <bank-uuid-or-name> \
    --account-type checking \
    --account-number 1234567890 \
    ~/Downloads/stmt.csv
```

### Routine import from BofA CSV (account already exists)

Since CSVs have no `ACCTID` to match on, the account must be identified explicitly:

```bash
uv run mibudge-import --account <account-uuid-or-name> \
    ~/Downloads/stmt.csv
```

### Dry run

Parse, validate, and check for duplicates without posting anything:

```bash
uv run mibudge-import --dry-run ~/Downloads/*.ofx
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
| `--config`                                 | TOML file of option values (see [Config file](#config-file)) |
| `--verbose, -v`                            | Debug logging                                               |
| `--plain`                                  | Disable rich terminal output (auto-detected when not a TTY) |

### Running the funding engine after import

The importer does **not** trigger funding automatically. If you want to fund budgets immediately after importing, pass `--run-funding`:

```bash
uv run mibudge-import ~/Downloads/*.ofx --run-funding
```

This calls `POST /api/v1/bank-accounts/<id>/run-funding/` after the import completes and prints the result (number of transfers, any warnings, skipped budget names). The flag is silently ignored on `--dry-run` runs.

Without `--run-funding`, funding still runs on each budget's schedule; see [`funding.md`](funding.md).

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

The live scraper logs into Bank of America using a Selenium/Firefox driver and syncs each BofA account that a mibudge account tracks.

### Installation

The scraper uses bofa-scraper and Selenium, from the `importers-bofa` dependency group, which `uv sync` installs by default, and needs Firefox installed on the host.

### Usage

```bash
uv run mibudge-bofa-live
```

The BofA login comes from `--bofa-id` (or `BOFA_ID`) and `--bofa-passcode`, then from the `username` and `password` fields of the [secret store](#secret-stores) `--bofa-creds-url` / `BOFA_CREDS_URL` names, and the scraper prompts for whichever is still missing. mibudge credentials come from the same [options](#credentials) as every tool.

If BofA requires 2FA, the scraper prompts for the code interactively via stdin. Run with `--no-headless` to watch the browser.

### Matching BofA accounts to mibudge accounts

A BofA account is imported into the mibudge account whose account number ends in the same last 4 digits. Only mibudge accounts in a bank whose name contains `--bank-name` (default `Bank of America`, case-insensitive) are tracked.

BofA's account overview shows only each account's nickname; the last 4 digits appear only once the account is opened. The importer keeps a nickname -> last-4 cache in the importers' config directory (default `~/.config/mibudge-importers/bofa-accounts.json`, or `--account-cache`), which is safe to sync between machines.

- An account whose nickname the cache maps to digits no tracked mibudge account has is skipped without being opened.
- An account with a new nickname, or one whose nickname another overview tile also uses, is opened and checked.
- When an opened account shows different digits than the cache holds, the cache is corrected. Every change is printed at the end of the run.
- An opened account that no mibudge account tracks is skipped. This is not an error.

If a tracked mibudge account is not found during a run, the importer warns and suggests `--check-all-accounts`. That option opens every BofA account regardless of the cache, rebuilds the mapping (dropping nicknames no longer on the overview), and reports what was added, changed or removed. The warning is not given for runs filtered with `--account` or cut short by BofA ending the session.

### Transaction details enrichment

For posted transactions BofA can serve a per-transaction detail record (merchant name, "CITY, ST" location, category, ISO 18245 MCC, masked virtual card number). After each account's `sync-scrape` POST, the server reports `details_needed` -- the rows whose DB transaction has never been enriched -- and the importer fetches those details while the scrape session is still open, then POSTs them to the `transaction-details` endpoint. The importer translates BofA's category string into a mibudge category full name (see Category mapping below) and submits it with each item; the server stores the raw dict, extracts the merchant columns, seeds the transaction's category (and its unassigned splits) when unassigned, and recomposes the display description ("Trader Joes -- Menlo Park, CA (Grocery Stores and Supermarkets)") unless the user has edited it.

**Merchant identity cleanup.** Card networks hide the real store behind a "soft descriptor" prefix for purchases routed through a payment platform (Square "SQ *", Toast "TST*", DoorDash "DD *DOORDASH ...", and others -- see `MerchantIntermediaryPattern` in the django-admin, admin-editable so a newly observed platform needs no code release). The server (`moneypools.service.merchant_enrichment`) recovers the real store into `merchant_name` and records the platform token in `merchant_intermediary`; the composed description appends the platform ("Blue Bottle Coffee -- Menlo Park, CA (Restaurants, via DoorDash)"). For direct purchases with no platform prefix, an extend-only pass recovers a DBA-name distinction BofA's own resolution can erase (e.g. "COSTCO GAS #10" recovering to "COSTCO GAS" rather than staying "COSTCO"). Rows enriched before this landed can be refreshed in place, from their stored `details` JSON, with no re-scrape:

```bash
uv run python app/manage.py reenrich_merchant_identity
uv run python app/manage.py reenrich_merchant_identity --account "Chase Checking" --dry-run
```

Two things keep this under BofA's rate limit (a burst of ~40-50 detail-dialog opens wedges the page and can kill the login session):

- **A run-wide fetch budget.** `--details-limit` (default 30) counts dialog opens across all accounts in the run, paced with empirically tuned delays and wedge recovery. Rows left over stay unenriched server-side and are re-reported by the next sync, so a backfill converges over successive runs. `--details-limit 0` disables detail fetching.
- **Merchant-copy.** BofA's details are stable per merchant, so each merchant is fetched only once per run; the merchant's other rows get a synthesized copy at zero dialog cost (provenance-marked `details_source: merchant-copy`, and without the per-transaction `virtual_card_number`). In practice a backfill costs one fetch per *merchant*, not per transaction.

### Saving scrape output

Pass `--save-dir <dir>` to write each account's raw scraped data to a JSON file (`YYYY-MM-DD-HHMMSS-<last4>.json`, format v4 -- the account's last 4 digits and fetched transaction details are included; `--save-only` saves every account, tracked or not). This lets you re-import from the saved file later without re-logging in to BofA. Combine with `--save-only` to capture the data on a machine that can reach BofA but not mibudge; add `--details-all` to force-capture the real detail dialog for every posted transaction (paced, no merchant-copy shortcut) so the file carries the full data:

```bash
# Capture on BofA-accessible machine:
uv run mibudge-bofa-live \
    --save-dir ./saved --save-only --details-all

# Replay later (also replays any saved details):
uv run mibudge-bofa-saved saved/*.json
```

### Flag reference

Every flag can also be set via its `MIBUDGE_FLAG_NAME` environment variable (see [Environment variables for every flag](#environment-variables-for-every-flag)). The two exceptions are noted below. The connection flags every tool shares are under [Credentials](#credentials).

| Flag | Purpose |
|------|---------|
| `--bofa-id` | BofA Online ID (env var: `BOFA_ID`, not `MIBUDGE_BOFA_ID`) |
| `--bofa-passcode` | BofA passcode (not read from the environment or the config file; prompted for when missing) |
| `--bofa-creds-url` | [Secret store](#secret-stores) holding the BofA `username` and `password` (env var: `BOFA_CREDS_URL`, not `MIBUDGE_BOFA_CREDS_URL`) |
| `--account, -a` | Filter by BofA account nickname substring or last-4 digits (repeatable; omit for all tracked accounts) |
| `--check-all-accounts` | Open every BofA account, rebuild the account cache, and report the changes |
| `--config` | TOML file of option values (default: `~/.config/mibudge-importers/config.toml`; see [Config file](#config-file)) |
| `--account-cache` | Nickname -> last-4 cache file (default: `~/.config/mibudge-importers/bofa-accounts.json`) |
| `--bank-name` | Substring of the mibudge Bank name whose accounts are tracked (default: `Bank of America`) |
| `--headless / --no-headless` | Run Firefox headlessly (default) or visibly for debugging/2FA |
| `--timeout` | Seconds to pause after each transaction details dialog, pacing requests to BofA (default: 5) |
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
  listed at the end of the run (its transactions land unassigned). See
  [When a run reports unmapped categories](#when-a-run-reports-unmapped-categories).

### When a run reports unmapped categories

A run ends with this notice when BofA used a category neither map knows:

```text
BofA categories with no mapping (their transactions were left unassigned):
'Shopping & Entertainment : Sporting Goods'.  Add them to a --category-map
overlay file or extend BOFA_CATEGORY_MAP in importers/bofa_categories.py.
```

Each quoted string is one BofA category. To map it:

1. **Choose the mibudge category.** The target is a category full name
   (`"{group} : {name}"`) visible to the user the importer signs in as.
   Search for one through the API:

   ```bash
   curl -s -H "Authorization: Api-Key $API_KEY" \
       "https://mibudge.example.com/api/v1/transaction-categories/?search=sporting" \
       | jq -r '.results[].full_name'
   ```

   The seeded base set is also listed in
   `app/moneypools/migrations/0038_seed_global_categories.py`. Use `null`
   as the target to leave the category unassigned on purpose, which also
   removes it from the notice.

2. **Add it to the overlay file.** Create
   `~/.config/mibudge-importers/categories.yaml`, or add a line to it:

   ```yaml
   'Shopping & Entertainment : Sporting Goods': 'Sports & Fitness : Sporting Goods'
   ```

   Paste the key exactly as the notice prints it; the loader normalizes
   its spacing and case. Quote both sides, because an unquoted colon is
   a YAML syntax error.

3. **Point the importers at the file**, once, with a top-level key in
   `~/.config/mibudge-importers/config.toml`:

   ```toml
   category_map = "categories.yaml"
   ```

   A relative path resolves against the config file's directory, and a
   top-level key applies to both `mibudge-bofa-live` and
   `mibudge-bofa-saved`. For a single run, pass `--category-map FILE` or
   set `MIBUDGE_CATEGORY_MAP`.

4. **Watch the next enrichment of that category.** The notice no longer
   lists a mapped category, whether or not the target is valid. A target
   that matches no visible category logs a warning for each transaction,
   and the transaction stays unassigned:

   ```text
   <bank account>: details <transaction uuid>: unknown category 'Sports & Fitness : Sport Goods'; transaction left unassigned
   ```

   Correct the target in the overlay file. The transactions that logged
   the warning are now in the position described next.

**A mapping applies only to transactions enriched after it is added.**
The importers submit details only for rows that have none, so the
transactions in the notice keep no category, and neither a later live
run nor a `mibudge-bofa-saved` replay revisits them.
`GET /api/v1/transactions/?bank_account=<id>&uncategorized=true` lists
the candidates, which include any other unassigned transactions in that
bank account.

Assigning them takes a staff login to the Django admin: a transaction's
change page edits its `category` and each of its allocations' categories.
Set both, because a transaction's category does not propagate to
allocations that already exist, and change nothing else on the form,
because a save there skips the budget balance accounting. Without staff
access, `PATCH /api/v1/transactions/<id>/` sets the transaction's
category only: allocations are read-only in the REST API, and the SPA has
no category editor.

To share a mapping with every deployment, add it to `BOFA_CATEGORY_MAP`
instead, keyed in normalized form
(`'shopping & entertainment:sporting goods'`). A unit test verifies every
built-in target names a seeded global category; the overlay can also name
your own categories, and it wins when both maps hold the same key.

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
uv run mibudge-backfill-budget \
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

Saved rules are stored in the importers' config directory, `~/.config/mibudge-importers/backfill-vendor-rules.json`, keyed by budget UUID.

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
| `--config`      | TOML file of option values (see [Config file](#config-file)) |
| `--verbose, -v` | Debug logging                            |
| `--plain`       | Disable rich terminal output             |

---

## Developer notes

Full developer documentation -- parser internals, adding new bank formats, multi-file dedup semantics, OFX balance derivation edge cases -- is in [`importers/README.md`](../importers/README.md).

To run the importer test suite:

```bash
uv run pytest importers/tests/ -v
```
