# importers/

Transaction importers for mibudge. These are **standalone scripts** that
interact with the mibudge backend exclusively through its REST API -- they
do not use the Django ORM, signals, or models directly.

## Why a separate directory?

Importers are intentionally isolated from the Django application (`app/`).
They authenticate via JWT (username/password to `/api/token/`) and
communicate only through the public API. This enforces a clean boundary:
the import concern stays separate from the core budgeting domain.

This directory will eventually be extracted into its own project/repository
once the import pipeline stabilizes. For now it lives here for convenience
(shared `pyproject.toml`, same CI pipeline, co-located tests).

## Structure

```
importers/
  __init__.py
  __main__.py           # python -m importers entry point
  client.py             # REST API client (auth, pagination, retries)
  import_transactions.py  # Main import script (click CLI)
  parsers/
    __init__.py
    bofa_csv.py         # Bank of America CSV export parser
  tests/
    __init__.py
    conftest.py         # Shared fixtures (bofa_csv_factory, client, mock_auth)
    test_client.py
    test_parsers.py
```

## Usage

The CLI is a click group with two subcommands: `import` (the main
transaction importer) and `banks` (list banks with their UUIDs, for
use with `--bank`). Connection/TLS/credential options live on the
group itself and apply to both subcommands.

```bash
# Import into an existing bank account (password from env var):
MIBUDGE_PASSWORD=secret uv run python -m importers \
    --username admin \
    import \
    --file ~/Downloads/stmt.csv \
    --account <bank-account-uuid>

# With .env file (auto-loaded):
echo "MIBUDGE_URL=http://localhost:8000" >> .env
echo "MIBUDGE_USERNAME=admin" >> .env
echo "MIBUDGE_PASSWORD=secret" >> .env
uv run python -m importers import -f ~/Downloads/stmt.csv -a <uuid>

# First-time import: create the bank account on the fly, seeded with
# the CSV's beginning balance. After the import, the account's posted
# balance is cross-checked against the CSV's ending balance.
uv run python -m importers banks    # list banks + UUIDs
uv run python -m importers import \
    -f ~/Downloads/stmt.csv \
    --create-account \
    --name "Personal Checking" \
    --bank <bank-uuid> \
    --account-type checking \
    --account-number 1234567890   # optional

# Against a local HTTPS dev server (mkcert-issued cert):
uv run python -m importers --trust-local-certs import -f stmt.csv -a <uuid>

# Or with an explicit CA bundle:
uv run python -m importers --ca-bundle "$(mkcert -CAROOT)/rootCA.pem" \
    import -f stmt.csv -a <uuid>

# With Vault:
export VAULT_ADDR=https://vault.example.com
export VAULT_TOKEN=s.xxxx
uv run python -m importers --vault-path mibudge/importer \
    import -f stmt.csv -a <uuid>
```

`--create-account` and `--account` are mutually exclusive. The
`--name`, `--bank`, `--account-type`, and `--account-number` flags
apply only when creating; supplying them with `--account` is an
error.

Before any API calls, the importer parses the CSV and walks the
running balance against the summary block; a corrupt or
internally-inconsistent file aborts the run without touching the
server.

Configuration resolution order (first wins):

1. CLI flags
2. Environment variables (`MIBUDGE_URL`, `MIBUDGE_USERNAME`, `MIBUDGE_PASSWORD`, etc.)
3. `.env` file (loaded via python-dotenv)
4. Vault KV2 secret (if `--vault-path` / `MIBUDGE_VAULT_PATH` is set)

## Adding a new bank parser

Each bank/format gets its own parser module under `importers/parsers/`. A
parser's `parse()` function takes a file path and returns a `ParsedStatement`
dataclass containing the summary metadata (beginning/ending balance and
dates, credit/debit totals) alongside the individual transactions:

```python
def parse(source: str | Path) -> ParsedStatement:
    ...
```

Parsers should also provide a `validate_statement(statement)` helper that
walks the running balance and cross-checks summary totals, returning a list
of human-readable error strings (empty if everything balances). The import
script calls this up front and refuses to proceed when the file fails its
own internal consistency check.

The import script handles deduplication, API communication, and progress
reporting -- parsers only need to extract structured data from raw files.

## Running tests

```bash
uv run pytest importers/tests/ -v
```
