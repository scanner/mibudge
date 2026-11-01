# importers/

Transaction importers for mibudge. These are **standalone scripts** that
interact with the mibudge backend exclusively through its REST API -- they
do not use the Django ORM, signals, or models directly.

## Why a separate directory?

Importers are intentionally isolated from the Django application (`app/`).
They authenticate with a mibudge **API key** (preferred; create one under
Settings -> API keys, sent as `Authorization: Api-Key <key>`) or via JWT
(email/password to `/api/token/`, legacy) and communicate only through
the public API. This enforces a clean boundary:
the import concern stays separate from the core budgeting domain.

This directory will eventually be extracted into its own project/repository
once the import pipeline stabilizes. For now it lives here for convenience
(shared `pyproject.toml`, same CI pipeline, co-located tests).

## Structure

```
importers/
  __init__.py
  __main__.py             # python -m importers entry point
  client.py               # REST API client (auth, pagination, retries)
  import_transactions.py  # Statement importer (click CLI): OFX/QFX + BofA CSV
  import_bofa_live.py     # BofA live scraper: Selenium login -> sync-scrape endpoint
  import_bofa_saved.py    # BofA saved-scrape replayer: JSON file -> sync-scrape endpoint
  backfill_budget.py      # Budget backfill: interactive month-by-month allocation
  config.py               # Shared config directory and config.toml (--config)
  secrets.py              # Secret stores: op:// (1Password), hcvault:// (Vault)
  parsers/
    __init__.py
    common.py             # Shared ParsedStatement / ParsedTransaction dataclasses
    bofa_csv.py           # Bank of America CSV export parser
    ofx.py                # OFX / QFX parser (any financial institution)
  tests/
    __init__.py
    conftest.py           # Fixture registry + file-writing fixtures
    factories.py          # factory_boy factories for per-row fixtures
    test_client.py
    test_factories.py
    test_parsers.py
```

## Supported file formats

| Extension      | Parser        | Carries account identity?                  |
|----------------|---------------|--------------------------------------------|
| `.csv`         | `bofa_csv.py` | No -- user must specify the target account |
| `.ofx`, `.qfx` | `ofx.py`      | Yes (OFX `ACCTID` + `ACCTTYPE`)            |

The importer dispatches by file extension. A single `mibudge-import` run
can mix formats in one run *for the same destination account*.

## CLI shape

Each tool is a single click command, installed as a console script by
`[project.scripts]` in `pyproject.toml`:

| Command                   | Module                | Config table        |
|---------------------------|-----------------------|---------------------|
| `mibudge-import`          | `import_transactions` | `[statements]`      |
| `mibudge-bofa-live`       | `import_bofa_live`    | `[bofa_live]`       |
| `mibudge-bofa-saved`      | `import_bofa_saved`   | `[bofa_saved]`      |
| `mibudge-backfill-budget` | `backfill_budget`     | `[backfill_budget]` |

Every command takes the same connection options
(`import_transactions.mibudge_options`) and `--config`
(`config.config_option`); a new command adds both and an entry in
`config.COMMANDS`.

`mibudge-import` takes statement files as positional args or via
`-f`, and both forms accept globs expanded by the shell:

    mibudge-import statements/*.ofx
    mibudge-import -f stmt1.ofx -f stmt2.ofx
    mibudge-import statements/*.ofx -f extra.csv

`--bank` takes a bank's name, UUID or routing number; when it does not
match exactly one bank, the importer lists the candidates.

`python -m importers` still runs `mibudge-import`. See
`docs/importers.md` for usage of every tool.

### Environment variables for every flag

Every command uses `auto_envvar_prefix="MIBUDGE"`, so every flag
automatically reads from a `MIBUDGE_FLAG_NAME` environment variable
when the flag is not set on the CLI.  Click derives the name as:
uppercase, hyphens replaced with underscores, `MIBUDGE_` prepended.
Examples: `--dry-run` → `MIBUDGE_DRY_RUN`; `--save-dir` →
`MIBUDGE_SAVE_DIR`.

The secret flags (`--api-key`, `--password`, `--bofa-passcode`) have
no environment variable and are never read from `.env` or the config
file: pass them as flags, or keep them in a secret store.  Three flags
override the prefix with explicit names: `--mibudge-creds-url` reads
`MIBUDGE_CREDS_URL`, and `import_bofa_live`'s `--bofa-id` and
`--bofa-creds-url` read `BOFA_ID` and `BOFA_CREDS_URL`.

Every command also reads option values from
`~/.config/mibudge-importers/config.toml`, below CLI flags and
environment variables; see `importers/config.py` and
[Configuration resolution](#configuration-resolution).

## Running the commands

`uv sync` (or `make uv-sync`) installs the four commands into the
checkout's `.venv/bin/`. Run them in one of three ways (here the
checkout is `~/src/mibudge`):

```bash
# From anywhere inside the checkout:
uv run mibudge-import ~/Downloads/*.ofx

# From any other directory, naming the checkout:
uv run --project ~/src/mibudge mibudge-import ~/Downloads/*.ofx

# Or by full path, with no uv involved:
~/src/mibudge/.venv/bin/mibudge-import ~/Downloads/*.ofx
```

`mibudge-bofa-live` also needs Firefox. Its Python dependencies
(bofa-scraper and Selenium) are the `importers-bofa` dependency group,
which `uv sync` installs by default.

All four read the `.env` at the root of the checkout, wherever they are
run from.

## Usage examples

Connection variables (`MIBUDGE_URL` and
`MIBUDGE_API_KEY_ONEPASSWORD_URL`, or `MIBUDGE_VAULT_PATH`) are
typically set in a `.env` file at the repo root and loaded
automatically; the examples below omit them for brevity.  An API key takes precedence over
email/password when both are present.  Note: API keys cannot call the
user/security endpoints (password/email change, invitations, key
management) -- those require an interactive login.

### Follow-up OFX/QFX import -- zero flags

For an account that already exists, the OFX `ACCTID` is matched
against `BankAccount.account_number` and the target account is
resolved automatically. This is the common case for routine monthly
imports -- just drop the files on the command line:

```bash
uv run mibudge-import ~/Downloads/*.ofx
```

Multiple statements for the same account are accepted in one run.
They are sorted by `beginning_date` (not by filename) and a warning
is emitted if consecutive statements leave a date gap.

### Initial OFX/QFX import -- create the account on the fly

First-time import from an OFX/QFX file. The account type and account
number are read from the OFX file itself, so only `--name` and
`--bank` are needed:

```bash
uv run mibudge-import --create-account \
    --name "Personal Checking" \
    --bank "Bank of America" \
    ~/Downloads/2025-*.ofx
```

The account's posted balance is seeded from the file's beginning
balance; after the import, it is cross-checked against the file's
ending balance.

As a safeguard, `--create-account` on a file whose `ACCTID` already
matches an existing `BankAccount.account_number` is refused -- drop
the `--create-account` flag and re-run to use the existing account.

### Initial BofA CSV import -- all flags required

BofA CSV exports do **not** carry an account identifier, so the
create-account flags must be supplied explicitly:

```bash
uv run mibudge-import --create-account \
    --name "Joint Checking" \
    --bank "Bank of America" \
    --account-type checking \
    --account-number 1234567890 \
    ~/Downloads/stmt.csv
```

### Follow-up BofA CSV import -- explicit `--account`

Because CSVs have no `ACCTID` to match on, follow-up imports must
name the target account by UUID:

```bash
uv run mibudge-import --account <bank-account-uuid> \
    ~/Downloads/stmt.csv
```

### Mixed-format single-account import

One `mibudge-import` run can combine CSV and OFX for the same account --
handy when migrating historical CSVs alongside current OFX exports:

```bash
uv run mibudge-import --account <uuid> \
    archive/2023-*.csv recent/2025-*.ofx
```

### Local HTTPS dev server

```bash
# Trust a locally-issued cert (mkcert):
uv run mibudge-import --trust-local-certs stmt.ofx

# Or point at an explicit CA bundle:
uv run mibudge-import --ca-bundle "$(mkcert -CAROOT)/rootCA.pem" stmt.ofx
```

### Credentials from a secret store

```bash
uv run mibudge-import --mibudge-creds-url op://Personal/mibudge stmt.ofx
uv run mibudge-import --mibudge-creds-url hcvault:///secret/mibudge stmt.ofx
```

The URL names one record: a 1Password item (`op://<vault>/<item>`,
read with the `op` CLI) or a HashiCorp Vault KV v2 secret
(`hcvault://<host>/<mount>/<path>`; no host means `VAULT_ADDR`, and the
token comes from `VAULT_TOKEN` or `~/.vault-token`).  The record's
`api_key` field is used, else its `password` with `--email`.  The BofA
live scraper's `--bofa-creds-url` names a second record, read for
`username` and `password`.  See `importers/secrets.py` and the
"Secret stores" section of `docs/importers.md`.

### BofA live scrape -- `mibudge-bofa-live`

Logs in to Bank of America and syncs every BofA account that a mibudge
bank account tracks. The BofA login comes from `--bofa-id` /
`--bofa-passcode`, then the secret store `--bofa-creds-url` names
(usually set in the config file's `[bofa_live]` table), and the command
prompts for whatever is still missing. A 2FA code is prompted for on
the terminal.

```bash
# Sync every tracked account:
uv run mibudge-bofa-live

# Preview one account (nickname substring or last 4 digits), with the
# browser visible:
uv run mibudge-bofa-live \
    --dry-run --account 1234 --no-headless

# Sync, keep the raw scrape, and run funding afterwards:
uv run mibudge-bofa-live \
    --save-dir ~/bofa-scrapes --run-funding
```

### Replay saved BofA scrapes -- `mibudge-bofa-saved`

Sends JSON files written by `mibudge-bofa-live --save-dir` through the
same sync, without logging in to BofA.

```bash
uv run mibudge-bofa-saved --dry-run ~/bofa-scrapes/2026-10-30-*.json
uv run mibudge-bofa-saved ~/bofa-scrapes/2026-10-30-*.json
```

### Backfill a budget -- `mibudge-backfill-budget`

Steps through a bank account's past transactions month by month and
asks, for each unallocated one, whether it belongs to a recurring
budget. Answers saved per vendor go in
`~/.config/mibudge-importers/backfill-vendor-rules.json`.

```bash
uv run mibudge-backfill-budget --account "Personal Checking" --budget "Groceries"
```

## Account resolution rules

The importer decides which `BankAccount` to POST transactions to
using this precedence (first win):

1. **`--account <uuid>` explicit.** Unambiguous; wins over everything.
2. **OFX `ACCTID` match.** For OFX/QFX inputs, the parser extracts
   `ACCTID` and the importer searches the caller's visible
   `BankAccount`s for one whose (client-decrypted) `account_number`
   matches. A single match resolves the account.
3. **`--create-account`.** A new `BankAccount` is created; for OFX
   inputs the account type and number come from the file, for CSV
   inputs they must be supplied via `--account-type` /
   `--account-number`.

Inconsistent combinations are rejected with a clear error rather than
silently guessing:

* `--account` + `--create-account` -- mutually exclusive.
* `--create-account` with a file whose `ACCTID` already matches an
  existing account -- refused (see the OFX safeguard above).
* Multiple OFX files in one run whose `ACCTID`s disagree -- refused.

## Flag reference (`mibudge-import`)

Every flag can also be set via its `MIBUDGE_FLAG_NAME` environment
variable (see [Environment variables for every flag](#environment-variables-for-every-flag)).

| Flag | Purpose |
|------|---------|
| positional paths / `-f, --file` | Statement files (CSV/OFX/QFX); both forms accepted, repeatable, combinable with shell globs. |
| `-a, --account <uuid>` | Existing `BankAccount` to import into. |
| `--create-account` | Create the destination account before importing. |
| `--name <str>` | Account name (create mode). |
| `--bank <uuid>` | Bank to link the account to (create mode). |
| `--account-type checking,savings,credit` | Account type (create mode, CSV only -- OFX supplies this). |
| `--account-number <str>` | Account number (create mode, CSV only -- OFX supplies this). |

## Pre-flight validation

Before any API calls, each parsed statement is walked for internal
consistency:

* **Running-balance walk.** Applying each transaction's signed amount
  to the preceding running balance must land on the statement's own
  running balance (CSV) or the parser-derived walk (OFX).
* **Summary totals** (CSV only). `beginning + credits + debits ==
  ending`.
* **Cross-file gap detection** (multi-file runs). Consecutive
  statements should meet at the same balance; a gap emits a warning
  but does not abort.

Internal inconsistency aborts the run without touching the server.

## Multi-file semantics

When a `mibudge-import` run combines several files, the importer flattens
them into one synthetic statement covering the full date range and
applies two further normalisations:

* **Intra-run transaction dedup.** Transactions that appear in more
  than one file (identical date, amount, and raw description) are
  kept only once. This covers both the common month-boundary overlap
  on monthly statements and the deliberate "download Jan -> Jun then
  Apr -> today" overlap pattern users tend to produce when pulling
  arbitrary date ranges. The server-side dedup catches re-imports but
  does nothing on a brand-new account, so the intra-run pass is
  what keeps newly-created accounts balanced. A rare false positive
  (two genuinely-distinct same-day, same-amount, same-description
  transactions) is dropped silently -- the alternative of posting
  phantom duplicates is much harder to untangle.

* **Derived combined beginning balance (OFX/QFX).** OFX exports
  carry only `LEDGERBAL`, and some FIs (Apple's exports are the
  known case) populate it with the balance *at the time of download*
  rather than the statement-end balance. When every file in a batch
  reports the same `LEDGERBAL`, each per-file beginning balance
  derived as `LEDGERBAL - sum(txs)` is nonsense. In that case the
  combined beginning balance is recomputed as `last.ending_balance
  - sum(unique_txs)` so the import chains cleanly. The
  transaction-level data remains authoritative in all cases --
  only the per-file *beginning* figure is treated as potentially
  unreliable. Sources that report a real beginning balance (BofA
  CSV summary block) are taken at face value.

## Progress feedback

Large multi-file runs can take tens of seconds in the parse and
dedup-fetch phases; the CLI renders rich progress bars and status
spinners throughout so the run never looks like a hang:

* A `Parsing <filename>` progress bar during the parse+validate
  loop (only shown for multi-file runs).
* A `Fetching existing transactions (<start> -> <end>)...` status
  spinner during the server-side dedup fetch.
* A per-transaction `Importing` progress bar during POST, annotated
  with running imported / skipped / failed counts.

Pass `--plain` to suppress the rich renderers (useful when the CLI
is invoked from scripts or CI). `--verbose` raises logging to DEBUG
and dumps the per-file summary table -- handy when a combined
statement doesn't balance and you need to see which file reports
which begin/end pair.

## Configuration resolution

Resolved in this order (first win):

1. CLI flags
2. Environment variables -- every flag has a `MIBUDGE_FLAG_NAME` equivalent
   (see [Environment variables for every flag](#environment-variables-for-every-flag))
3. `.env` file (loaded via python-dotenv)
4. `~/.config/mibudge-importers/config.toml` (or `--config` /
   `MIBUDGE_CONFIG`): the command's own table, then the top level
5. The option's built-in default

The API key and password are then taken from the flags, else from the
secret store `--mibudge-creds-url` names.

## Adding a new bank parser

Each bank/format gets its own parser module under `importers/parsers/`.
A parser's `parse()` function takes a file path and returns a
`ParsedStatement` dataclass (see `parsers/common.py`) containing the
summary metadata (beginning/ending balance and dates, credit/debit
totals), the individual transactions, and -- when the source format
carries them -- the account identifier (`acct_id`) and account type
code (`"C"`/`"S"`/`"X"`):

```python
def parse(source: str | Path) -> ParsedStatement:
    ...
```

Parsers also provide a `validate_statement(statement)` helper that
walks the running balance (and any summary totals the format carries),
returning a list of human-readable error strings (empty if everything
balances). The import script calls this up front and refuses to
proceed when the file fails its own internal consistency check.

Register the parser in the extension dispatch table in
`import_transactions.py`:

```python
_PARSERS = {
    ".csv": (bofa_csv.parse, bofa_csv.validate_statement),
    ".ofx": (ofx.parse, ofx.validate_statement),
    ".qfx": (ofx.parse, ofx.validate_statement),
}
```

The import script handles deduplication, account resolution, API
communication, and progress reporting -- parsers only need to extract
structured data from raw files.

## Running tests

```bash
uv run pytest importers/tests/ -v
```

Test fixtures follow the project's factory_boy + pytest_factoryboy
pattern (see `tests/factories.py`). Per-row factories
(`BofaCSVRowFactory`, `OFXTxnSpecFactory`) are exposed as
`bofa_csv_row_factory` / `ofx_txn_spec_factory` fixtures; file-level
fixtures (`bofa_csv_factory`, `ofx_file_factory`) build on them to
write full statement files to `tmp_path`.
