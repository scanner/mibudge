"""
Backfill budget allocations for a recurring or capped budget, month by month.

This script walks the full transaction history for a bank account, grouped
by calendar month, and interactively allocates transactions to a chosen
budget.  It maintains the budget's funding schedule at period boundaries.

Typical usage::

    uv run python -m importers.backfill_budget \\
        --account "Personal Checking" \\
        --budget "Groceries"

For each unallocated transaction the script:

  1. Parses a human-readable vendor name from the raw bank description.
  2. Checks whether a "always allocate" rule is already stored for this vendor
     (from a previous run's choice).
  3. If no auto-rule matches: prompts ``y / n / a / s / q``.
  4. On ``y`` or ``a``: calls the split API on the transaction so that the
     full amount is allocated to the target budget with a correct
     ``budget_balance`` snapshot.
  5. At the start and at the end of each period: funds the budget from
     Unallocated according to its type:

     * Recurring (R): tops up to ``target_balance`` at every period boundary.
     * Capped (C): fills to ``target_balance`` initially, then adds the
       fixed ``funding_amount`` per period (never exceeding ``target_balance``).

Vendor auto-rules are stored in ``~/.mibudge/vendor_rules.json`` and
persist across runs, keyed by budget UUID.

Connection configuration follows the same precedence as the transaction
importer (CLI flags → env vars → .env file → Vault).
"""

# system imports
import bisect
import calendar
import json
import logging
import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

# 3rd party imports
import click
from dateutil.rrule import rrulestr
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table

# Project imports
from importers.client import APIError, AuthenticationError, MibudgeClient
from importers.import_transactions import (
    _build_client,
    _resolve_account_by_query,
    _setup_logging,
)
from importers.theme import _Theme, get_theme, theme_option

logger = logging.getLogger(__name__)

########################################################################
########################################################################
#
# Persistent vendor auto-rule storage.
#
# Structure on disk:
#   {
#     "<budget_uuid>": {
#       "normalized vendor name": true   # always allocate
#     }
#   }
#
_RULES_PATH = Path.home() / ".mibudge" / "vendor_rules.json"

# MM/DD purchase date embedded in many card descriptions
_DESC_DATE_RE = re.compile(r"\b\d{1,2}/\d{1,2}\b")

# RFC 5545 DTSTART line (with optional parameters before the colon)
_DTSTART_RE = re.compile(
    r"DTSTART(?:;[^:]*)?:(\d{4})(\d{2})(\d{2})", re.IGNORECASE
)
# RRULE FREQ value
_FREQ_RE = re.compile(r"FREQ=(\w+)", re.IGNORECASE)

# Trailing noise tokens to strip when no date pattern is found
_NOISE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\s+MOBILE\s+PURCHASE.*$", re.IGNORECASE),
    re.compile(r"\s+ONLINE\s+PURCHASE.*$", re.IGNORECASE),
    re.compile(r"\s+DEBIT\s*.*$", re.IGNORECASE),
    re.compile(r"\s+PURCHASE.*$", re.IGNORECASE),
    # "Bill Payment" appended by some billers (e.g. Comcast, AT&T)
    re.compile(r"\s+Bill\s+Payment\s*$", re.IGNORECASE),
    # Card/store number suffix like "#10123"
    re.compile(r"\s+#\d+\s*$"),
]

# Short all-caps processor codes that appear before '*' but are NOT the vendor.
# Everything after the '*' is the real vendor name in these cases.
# Examples: TST (Toast), SQ (Square), OLO (OLO ordering), PAR (PAR POS),
#           PY, DD (DoorDash), WEB, FSP, PP (PayPal legacy).
_PROCESSOR_CODE_RE = re.compile(r"^[A-Z]{1,5}$")

# An "order ID" is a reference code rather than a vendor name.
# Heuristic: a single token that mixes letters AND digits (e.g. "NJ6FA7G40",
# "B757G0SE1", "1ZMHTXXXXX32944103") or is all digits.  Pure-alpha tokens
# like "COLOROFCHANGE" or "Membership" are NOT order IDs.
_ORDER_ID_RE = re.compile(
    r"^(?=[A-Z0-9]*[A-Z][A-Z0-9]*[0-9]|[0-9]+$)[A-Z0-9]{5,}$"
)


########################################################################
########################################################################
#
def _looks_like_order_id(word: str) -> bool:
    """
    Return True if *word* looks like a reference code rather than a vendor name.

    Order IDs and tracking numbers mix uppercase letters with digits (e.g.
    ``NJ6FA7G40``, ``1ZMHTXXXXX32944103``, ``B757G0SE1``).  Pure-alpha tokens
    (``COLOROFCHANGE``, ``Membership``) are not order IDs even if long.

    Args:
        word: A single whitespace-free token.

    Returns:
        True when the token looks like an order ID / tracking number.
    """
    return bool(_ORDER_ID_RE.match(word))


####################################################################
#
def _clean_vendor_text(desc: str) -> str:
    """
    Apply final cleanup to a raw vendor string before title-casing.

    * Replaces underscores with spaces (``ACTBLUE_CHARITABLECONT``).
    * Collapses multiple whitespace runs.
    * Strips trailing commas, semicolons, colons, hyphens, and spaces.
      Does NOT strip trailing ``'.'`` so that abbreviations like ``Inc.``
      are preserved.

    Args:
        desc: The partially-cleaned vendor string.

    Returns:
        A title-cased vendor string, or ``"Unknown"`` if nothing remains.
    """
    desc = desc.replace("_", " ")
    desc = re.sub(r"\s+", " ", desc).strip()
    desc = desc.strip(" ,;:-")
    return desc.title() if desc else "Unknown"


########################################################################
########################################################################
#
def _extract_vendor(raw_description: str) -> str:
    """
    Extract a human-readable vendor name from a raw bank description.

    Handles the following common patterns from BofA / card networks:

    * ``TST*CAFE BORRONE 03/28 MOBILE PURCHASE Menlo Park CA``
      → "Cafe Borrone"   (processor prefix ``TST`` before ``*``)
    * ``AMAZON MKTPL*NJ6FA7G40 09/24 PURCHASE Amzn.com/bill WA``
      → "Amazon Mktpl"   (order-ID after ``*`` → use company name before)
    * ``Patreon* Membership 04/01 PURCHASE Internet``
      → "Patreon"        (known company before ``*``, not a processor code)
    * ``AppOmni, Inc. DES:PAYROLL ID:CERXXXXX0847028 INDN:…``
      → "Appomni, Inc."  (ACH/payroll record: truncate at ``DES:``)
    * ``COMCAST CABLE COMMUNICATIONS Bill Payment``
      → "Comcast Cable Communications"  (strip " Bill Payment" suffix)
    * ``APTIVE ENVIRONMENTAL 4931 NORTH 300 WEST PROVO 84604 UT USA``
      → "Aptive Environmental"  (truncate at embedded street number)
    * ``ACTBLUE_CHARITABLECONT 10/31 PURCHASE HTTPSSECURE.A MA``
      → "Actblue Charitablecont"  (underscore → space, truncate at date)

    Args:
        raw_description: The raw description string from the bank record.

    Returns:
        A cleaned, title-cased vendor name.  Falls back to the raw description
        (title-cased) if nothing useful can be extracted.
    """
    desc = raw_description.strip()

    # --- Step 1: ACH / payroll / electronic-payment records ---
    # "AppOmni, Inc. DES:PAYROLL ID:…"  →  "AppOmni, Inc."
    # The text before " DES:" is always the originating company name.
    des_m = re.search(r"\s+DES:", desc, re.IGNORECASE)
    if des_m:
        return _clean_vendor_text(desc[: des_m.start()])

    # --- Step 2: "Bill Payment" suffix ---
    # "COMCAST CABLE COMMUNICATIONS Bill Payment"  →  "COMCAST CABLE COMMUNICATIONS"
    bp_m = re.search(r"\s+Bill\s+Payment\s*$", desc, re.IGNORECASE)
    if bp_m:
        return _clean_vendor_text(desc[: bp_m.start()])

    # --- Step 3: '*' separator ---
    # The '*' can mean two different things:
    #   a) Processor code before '*': "TST*CAFE BORRONE" → vendor is AFTER
    #   b) Company name before '*':   "AMAZON MKTPL*NJ6FA7G40" → vendor is BEFORE
    #
    # Disambiguation heuristics (applied in order):
    #   1. If the first token AFTER '*' looks like an order/tracking ID
    #      (mixes uppercase letters and digits, ≥ 5 chars), the real vendor
    #      is the text BEFORE '*' (e.g. "AMAZON MKTPL", "Kindle Svcs").
    #   2. Else if the text BEFORE '*' is a short all-caps code (≤ 5 letters,
    #      no digits or spaces), it is a processor prefix and the vendor is
    #      AFTER (e.g. "TST", "SQ", "OLO", "PAR", "FSP", "DD", "WEB").
    #   3. Otherwise the text BEFORE '*' is the company/vendor (e.g. "Patreon",
    #      "ACTBLUE", "GRUBHUB", "VIATOR").
    if "*" in desc:
        before, after = desc.split("*", 1)
        before = before.strip()
        after = after.strip()
        after_first = after.split()[0] if after.split() else ""

        if _looks_like_order_id(after_first):
            # Order ID after '*' → company name is before.
            # e.g. "AMAZON MKTPL*NJ6FA7G40" → "AMAZON MKTPL"
            desc = before
        elif re.match(r"^BILL\s+PAYMENT\b", after, re.IGNORECASE):
            # Bill-payment charge: the company is named before '*'.
            # e.g. "ATT* BILL PAYMENT 04/03 …" → "ATT"
            desc = before
        elif _PROCESSOR_CODE_RE.match(before):
            # Short processor code before '*' → vendor name is after.
            # e.g. "TST*CAFE BORRONE" → "CAFE BORRONE"
            desc = after
        else:
            # Longer company/brand name before '*' → that IS the vendor.
            # e.g. "Patreon* Membership", "ACTBLUE* COLOROFCHANGE"
            desc = before

    # --- Step 4: Embedded purchase date (MM/DD) ---
    # Card networks embed the purchase date in the description.
    # Everything after it is noise (purchase type, city, state, phone).
    m = _DESC_DATE_RE.search(desc)
    if m:
        return _clean_vendor_text(desc[: m.start()])

    # --- Step 5: Street address number (4+ digits followed by a word) ---
    # "APTIVE ENVIRONMENTAL 4931 NORTH 300 WEST …"  →  "APTIVE ENVIRONMENTAL"
    addr_m = re.search(r"\s+\d{4,}\s+\S", desc)
    if addr_m:
        return _clean_vendor_text(desc[: addr_m.start()])

    # --- Step 6: Strip known trailing noise patterns ---
    for pattern in _NOISE_PATTERNS:
        desc = pattern.sub("", desc).strip()

    return _clean_vendor_text(desc)


####################################################################
#
def _normalize_vendor(vendor: str) -> str:
    """
    Normalize a vendor name to a stable key for rule matching.

    Args:
        vendor: Human-readable vendor name (possibly title-cased).

    Returns:
        Lower-cased, stripped vendor name.
    """
    return vendor.lower().strip()


########################################################################
########################################################################
#
def _parse_recurrance_schedule(
    rec_str: str | None,
) -> tuple[str | None, date | None]:
    """
    Extract FREQ and DTSTART from a recurrence field string.

    Args:
        rec_str: RFC 5545 recurrence string from the budget API, or None.

    Returns:
        ``(freq, dtstart)`` where *freq* is the uppercase FREQ value (e.g.
        ``'MONTHLY'``, ``'YEARLY'``) and *dtstart* is the parsed
        :class:`~datetime.date`, or ``(None, None)`` if either field is
        absent or cannot be parsed.
    """
    if not rec_str:
        return None, None
    freq: str | None = None
    dtstart: date | None = None
    m = _DTSTART_RE.search(rec_str)
    if m:
        try:
            dtstart = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    m = _FREQ_RE.search(rec_str)
    if m:
        freq = m.group(1).upper()
    return freq, dtstart


####################################################################
#
def _cycle_year_for_date(
    d: date,
    reset_month: int,
    reset_day: int,
) -> int:
    """
    Return the cycle year that *d* belongs to for an annual budget.

    A cycle starts on ``(reset_month, reset_day)`` of each calendar year.
    If *d* falls on or after that reset date in its year, it belongs to
    that year's cycle; otherwise it belongs to the previous year's cycle.

    Args:
        d:            Transaction date.
        reset_month:  Month of the annual reset (1--12).
        reset_day:    Day of the annual reset (clamped to the month length
                      in non-leap years for Feb 29 etc.).

    Returns:
        The cycle year (the year in which the cycle started).
    """
    try:
        reset_this_year = date(d.year, reset_month, reset_day)
    except ValueError:
        # e.g. Feb 29 in a non-leap year -- clamp to last day of month
        last_day = calendar.monthrange(d.year, reset_month)[1]
        reset_this_year = date(d.year, reset_month, min(reset_day, last_day))
    return d.year if d >= reset_this_year else d.year - 1


########################################################################
########################################################################
#
def _load_rules(budget_id: str) -> dict[str, bool]:
    """
    Load vendor auto-allocation rules for this budget from disk.

    Args:
        budget_id: UUID of the target budget.

    Returns:
        Dict mapping normalized vendor name to a bool: ``True`` means
        always allocate, ``False`` means always skip.
        Empty dict if the file does not exist or cannot be read.
    """
    if not _RULES_PATH.exists():
        return {}
    try:
        data: dict[str, Any] = json.loads(_RULES_PATH.read_text())
        return dict(data.get(budget_id, {}))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(
            "Could not load vendor rules from %s: %s", _RULES_PATH, e
        )
        return {}


####################################################################
#
def _save_rules(budget_id: str, rules: dict[str, bool]) -> None:
    """
    Persist vendor auto-allocation rules for this budget to disk.

    Merges with any existing rules for other budgets in the same file
    so that multiple budgets can share the rules file without clobbering
    each other.

    Args:
        budget_id: UUID of the target budget.
        rules: Dict mapping normalized vendor name to a bool (``True``
            = always allocate, ``False`` = always skip).
    """
    _RULES_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, Any] = {}
    if _RULES_PATH.exists():
        try:
            existing = json.loads(_RULES_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    existing[budget_id] = rules
    try:
        _RULES_PATH.write_text(json.dumps(existing, indent=2, sort_keys=True))
    except OSError as e:
        logger.warning("Could not save vendor rules to %s: %s", _RULES_PATH, e)


########################################################################
########################################################################
#
def _resolve_budget(
    client: MibudgeClient,
    bank_account_id: str,
    query: str,
    *,
    console: Console,
) -> dict[str, Any]:
    """
    Match *query* against budgets in the bank account and return the dict.

    Resolution order (first match wins):

    1. Exact case-insensitive name match — "Eating Out" will not also pick up
       "Eating Out Fill-up" even though "eating out" is a substring of both.
    2. Exact UUID match.
    3. Case-insensitive substring match — used when the exact name is not
       found and the user supplied a fragment.

    If exactly one budget matches at the winning tier it is returned.
    Otherwise a disambiguation table is printed and a
    :class:`click.ClickException` is raised.

    Args:
        client:          Authenticated MibudgeClient.
        bank_account_id: UUID of the bank account to search.
        query:           User-supplied name fragment or UUID.
        console:         Rich console for user-visible messages.

    Returns:
        The matched budget dict from the API.

    Raises:
        click.ClickException: On zero or multiple matches.
    """
    all_budgets = list(
        client.get_all("/api/v1/budgets/", {"bank_account": bank_account_id})
    )
    q = query.lower()

    # Tier 1: exact name match (case-insensitive).
    exact = [b for b in all_budgets if (b.get("name") or "").lower() == q]
    if len(exact) == 1:
        b = exact[0]
        console.print(f"[dim]Matched budget '{b['name']}' ({b['id']}).[/dim]")
        return b

    # Tier 2: exact UUID match.
    uuid_exact = [b for b in all_budgets if (b.get("id") or "") == query]
    if len(uuid_exact) == 1:
        b = uuid_exact[0]
        console.print(f"[dim]Matched budget '{b['name']}' ({b['id']}).[/dim]")
        return b

    # Tier 3: substring match.
    matches = [b for b in all_budgets if q in (b.get("name") or "").lower()]

    if len(matches) == 1:
        b = matches[0]
        console.print(f"[dim]Matched budget '{b['name']}' ({b['id']}).[/dim]")
        return b

    if not matches:
        show = all_budgets
        msg = f"No budgets match {query!r}."
    else:
        show = matches
        msg = f"Multiple budgets match {query!r}; be more specific."

    table = Table(title="Budgets")
    table.add_column("Name", style="bold")
    table.add_column("Type")
    table.add_column("Balance")
    table.add_column("UUID", style="dim")
    for b in show:
        table.add_row(
            b.get("name", ""),
            b.get("budget_type", ""),
            b.get("balance", ""),
            b.get("id", ""),
        )
    console.print(table)
    raise click.ClickException(msg)


########################################################################
########################################################################
#
def _enumerate_schedule_dates(
    sched_str: str,
    start: date,
    end: date,
) -> list[date]:
    """
    Return all dates in [*start*, *end*] on which *sched_str* fires.

    Parses the RFC 2445 recurrence string returned by the budget API using
    dateutil, then collects every generated date in the requested window.
    Returns an empty list on parse failure so callers fall back gracefully.

    Args:
        sched_str: RFC 2445 string (e.g. ``'RRULE:FREQ=MONTHLY;BYMONTHDAY=15,-1'``).
        start:     Inclusive lower bound (first transaction date).
        end:       Inclusive upper bound (last transaction date).

    Returns:
        Sorted list of dates on which the schedule fires within [start, end].
    """
    start_dt = datetime(start.year, start.month, start.day)
    end_dt = datetime(end.year, end.month, end.day, 23, 59, 59)
    try:
        ruleset = rrulestr(
            sched_str,
            dtstart=start_dt,
            ignoretz=True,
            forceset=True,
        )
        return sorted(
            {dt.date() for dt in ruleset.between(start_dt, end_dt, inc=True)}
        )
    except Exception as e:
        logger.warning("Could not parse schedule %r: %s", sched_str, e)
        return []


########################################################################
########################################################################
#
def _fund_by_amount(
    client: MibudgeClient,
    budget: dict[str, Any],
    unallocated_id: str,
    bank_account_id: str,
    funding_amount: Decimal,
    cap_balance: Decimal,
    *,
    console: Console,
    label: str = "",
) -> None:
    """
    Credit the budget by a fixed *funding_amount*, never exceeding *cap_balance*.

    Fetches the current balance, computes
    ``transfer = min(funding_amount, cap_balance - balance)``, and creates
    an InternalTransaction from Unallocated if the transfer is positive.

    Args:
        client:           Authenticated MibudgeClient.
        budget:           Budget dict (must have ``'id'`` and ``'name'``).
        unallocated_id:   UUID of the account's Unallocated budget.
        bank_account_id:  UUID of the bank account.
        funding_amount:   Fixed amount to add per funding event.
        cap_balance:      Hard ceiling -- the balance will never exceed this.
        console:          Rich console for user-visible messages.
        label:            Optional prefix string for the log line.
    """
    fresh = client.get(f"/api/v1/budgets/{budget['id']}/")
    raw_balance = fresh.get("balance") or "0"
    balance = Decimal(str(raw_balance)).quantize(Decimal("0.01"))
    cap = cap_balance.quantize(Decimal("0.01"))

    headroom = cap - balance
    if headroom <= 0:
        console.print(
            f"[dim]{label}'{budget['name']}' already at cap "
            f"(balance={balance}, cap={cap}).[/dim]"
        )
        return

    transfer = min(funding_amount, headroom).quantize(Decimal("0.01"))
    if transfer <= 0:
        return

    console.print(
        f"[bold success]{label}Funding[/bold success] '{budget['name']}': "
        f"+[success]{transfer}[/success]  "
        f"([dim]{balance} → {balance + transfer}[/dim])"
    )
    try:
        client.post(
            "/api/v1/internal-transactions/",
            {
                "bank_account": bank_account_id,
                "src_budget": unallocated_id,
                "dst_budget": budget["id"],
                "amount": str(transfer),
            },
        )
    except APIError as e:
        console.print(f"[error]Failed to fund budget: {e}[/error]")


########################################################################
########################################################################
#
def _fund_to_target(
    client: MibudgeClient,
    budget: dict[str, Any],
    unallocated_id: str,
    bank_account_id: str,
    funding_amount: Decimal,
    *,
    console: Console,
    label: str = "",
) -> None:
    """
    Top up the budget from the Unallocated budget to reach *funding_amount*.

    Fetches the current budget balance, computes the deficit, and creates an
    InternalTransaction from Unallocated → target budget if needed.

    Args:
        client:           Authenticated MibudgeClient.
        budget:           Budget dict (must have ``'id'`` and ``'name'``).
        unallocated_id:   UUID of the account's Unallocated budget.
        bank_account_id:  UUID of the bank account.
        funding_amount:   Target balance to fund up to.
        console:          Rich console for user-visible messages.
        label:            Optional prefix string for the log line.
    """
    fresh = client.get(f"/api/v1/budgets/{budget['id']}/")
    raw_balance = fresh.get("balance") or "0"
    balance = Decimal(str(raw_balance)).quantize(Decimal("0.01"))
    target = funding_amount.quantize(Decimal("0.01"))

    if balance >= target:
        console.print(
            f"[dim]{label}'{budget['name']}' already funded "
            f"(balance={balance}, target={target}).[/dim]"
        )
        return

    deficit = (target - balance).quantize(Decimal("0.01"))
    console.print(
        f"[bold success]{label}Funding[/bold success] '{budget['name']}': "
        f"+[success]{deficit}[/success]  "
        f"([dim]{balance} → {target}[/dim])"
    )
    try:
        client.post(
            "/api/v1/internal-transactions/",
            {
                "bank_account": bank_account_id,
                "src_budget": unallocated_id,
                "dst_budget": budget["id"],
                "amount": str(deficit),
            },
        )
    except APIError as e:
        console.print(f"[error]Failed to fund budget: {e}[/error]")


########################################################################
########################################################################
#
def _allocate_to_budget(
    client: MibudgeClient,
    tx: dict[str, Any],
    target_budget_id: str,
    *,
    console: Console,
) -> bool:
    """
    Use the splits API to allocate the full transaction amount to the target budget.

    Calls ``POST /api/v1/transactions/<id>/splits/`` with the full
    absolute amount assigned to *target_budget_id*.  The backend deletes
    the old Unallocated allocation, creates a new one for the target
    budget, and records the correct ``budget_balance`` snapshot at
    operation time — something a plain PATCH cannot do.

    Args:
        client:           Authenticated MibudgeClient.
        tx:               Transaction dict from the API (must have ``id``
                          and ``amount``).
        target_budget_id: UUID of the target budget.
        console:          Rich console for user-visible messages.

    Returns:
        True on success, False on API error.
    """
    tx_id = str(tx["id"])
    raw_amount = tx.get("amount") or "0"
    abs_amount = str(abs(Decimal(str(raw_amount))))
    try:
        client.post(
            f"/api/v1/transactions/{tx_id}/splits/",
            {"splits": {target_budget_id: abs_amount}},
        )
        return True
    except APIError as e:
        console.print(f"[error]  Allocation failed: {e}[/error]")
        return False


########################################################################
########################################################################
#
def _parse_tx_date(iso_string: str) -> date:
    """
    Parse the ISO datetime string returned by the transaction API into a date.

    Args:
        iso_string: ISO datetime like ``"2025-01-15T00:00:00Z"``.

    Returns:
        The date portion.
    """
    return datetime.fromisoformat(iso_string.replace("Z", "+00:00")).date()


####################################################################
#
def _format_amount(amount_str: str) -> str:
    """
    Format a transaction amount string for display.

    Negative amounts (debits) are shown in red; positive (credits) in green.

    Args:
        amount_str: String representation of the amount (e.g. ``"-12.50"``).

    Returns:
        Rich markup string.
    """
    try:
        val = Decimal(str(amount_str))
    except Exception:
        return amount_str
    if val < 0:
        return f"[money_neg]{val:+.2f}[/money_neg]"
    return f"[money_pos]+{val:.2f}[/money_pos]"


########################################################################
########################################################################
#
def _prompt_user(
    console: Console,
    tx: dict[str, Any],
    vendor: str,
    budget_name: str,
    auto_rule: bool | None,
) -> str:
    """
    Display the transaction and prompt the user for an allocation decision.

    Args:
        console:     Rich console.
        tx:          Transaction dict from the API.
        vendor:      Extracted vendor name.
        budget_name: Name of the target budget.
        auto_rule:   Pre-existing auto-rule value, or None if no rule exists.

    Returns:
        One of ``'y'``, ``'n'``, ``'a'``, ``'s'``, ``'q'``
        (yes / no / always / skip-all-from-this-vendor / quit).
    """
    tx_date = _parse_tx_date(tx["transaction_date"])
    amount_str = tx.get("amount") or "0"
    raw_desc = tx.get("raw_description") or ""
    amount_display = _format_amount(str(amount_str))

    console.print(
        f"  [bold]{tx_date}[/bold]  {amount_display}  [accent]{vendor}[/accent]"
    )
    console.print(f"  [dim]{raw_desc}[/dim]")

    if auto_rule is True:
        console.print("  [dim]→ auto-allocating (rule)[/dim]")
        return "y"

    while True:
        try:
            raw = (
                console.input(
                    f"  Allocate to [bold]{budget_name}[/bold]? "
                    "[bold]y[/bold]/[bold]n[/bold]/"
                    "[bold]a[/bold](lways)/"
                    "[bold]s[/bold](kip vendor)/"
                    "[bold]q[/bold](uit)  "
                )
                .strip()
                .lower()
            )
        except (EOFError, KeyboardInterrupt):
            return "q"
        if raw in ("y", "n", "a", "s", "q"):
            return raw
        if raw in ("?", "h", "help"):
            console.print(
                "  [dim]"
                "y = yes, allocate this transaction\n"
                "  n = no, leave as Unallocated\n"
                "  a = always allocate from this vendor to this budget\n"
                "  s = skip all remaining transactions from this vendor today\n"
                "  q = quit (saves rules, stops processing)"
                "[/dim]"
            )


########################################################################
########################################################################
#
def _process_month(
    year: int,
    month: int,
    candidates: list[tuple[dict[str, Any], str]],
    client: MibudgeClient,
    target_budget: dict[str, Any],
    rules: dict[str, bool],
    skip_vendors: set[str],
    *,
    console: Console,
    theme: _Theme,
    period_label: str | None = None,
) -> tuple[int, int, int, bool]:
    """
    Interactively process one period's candidate transactions.

    For each candidate transaction the user is prompted to allocate it to the
    target budget. Auto-rules (from previous "always" choices) are applied
    without prompting.

    Args:
        year, month:     Calendar year and month being processed (used only
                         when *period_label* is not provided).
        candidates:      List of ``(transaction_dict, allocation_uuid)`` pairs.
                         Only transactions with a single Unallocated allocation
                         are included.
        client:          Authenticated MibudgeClient.
        target_budget:   Budget dict for the allocation target.
        rules:           Mutable vendor auto-rule dict (modified in place).
        skip_vendors:    Mutable set of vendors to skip for the session.
        console:         Rich console.
        period_label:    Optional display label overriding the default
                         ``"Month Year"`` format (used for yearly budgets).

    Returns:
        ``(allocated, skipped, auto_allocated, quit_requested)`` where
        *quit_requested* is True if the user pressed ``q``.
    """
    label = period_label or f"{calendar.month_name[month]} {year}"
    console.print(
        Rule(
            f"[bold]{label}[/bold]  "
            f"({len(candidates)} candidate transaction(s))",
            style=theme.rule_style,
        )
    )

    allocated = 0
    skipped = 0
    auto_allocated = 0

    for tx, _alloc_id in candidates:
        raw_desc = tx.get("raw_description") or ""
        vendor = _extract_vendor(raw_desc)
        vendor_key = _normalize_vendor(vendor)

        # Skip vendors flagged either this session or by a saved rule.
        if vendor_key in skip_vendors:
            console.print(f"  [dim]skipping {vendor} (skip rule)[/dim]")
            skipped += 1
            continue

        auto_rule: bool | None = rules.get(vendor_key)
        choice = _prompt_user(
            console, tx, vendor, target_budget["name"], auto_rule
        )

        if choice == "q":
            return allocated, skipped, auto_allocated, True

        if choice == "s":
            skip_vendors.add(vendor_key)
            rules[vendor_key] = False
            console.print(f"  [dim]Saved rule: always skip '{vendor}'.[/dim]")
            skipped += 1
            continue

        if choice in ("y", "a"):
            if choice == "a":
                rules[vendor_key] = True
                console.print(
                    f"  [dim]Saved rule: always allocate '{vendor}' → "
                    f"'{target_budget['name']}'.[/dim]"
                )
            ok = _allocate_to_budget(
                client, tx, target_budget["id"], console=console
            )
            if ok:
                if auto_rule is True:
                    auto_allocated += 1
                else:
                    allocated += 1
            else:
                skipped += 1
        else:  # 'n'
            skipped += 1
            console.print("  [dim]Skipped.[/dim]")

    return allocated, skipped, auto_allocated, False


########################################################################
########################################################################
#
def _run_backfill(
    client: MibudgeClient,
    bank_account_id: str,
    target_budget: dict[str, Any],
    unallocated_id: str,
    funding_amount: Decimal,
    *,
    budget_type: str = "R",
    cap_balance: Decimal | None = None,
    sched_str: str | None = None,
    yearly: bool = False,
    reset_month: int = 1,
    reset_day: int = 1,
    console: Console,
    theme: _Theme,
) -> None:
    """
    Run the full period-by-period backfill loop for the target budget.

    When *yearly* is False (the default) periods are calendar months and
    the budget is topped up at the end of each month.  When *yearly* is
    True, periods are annual cycles starting on ``(reset_month, reset_day)``
    and the budget is topped up once at the end of each cycle year.

    Funding behavior at period boundaries differs by type:

    * Recurring (R): ``_fund_to_target`` -- tops up to ``funding_amount``
      (which equals ``target_balance`` for recurring budgets).
    * Capped (C): ``_fund_by_amount`` -- adds ``funding_amount`` but never
      exceeds ``cap_balance`` (``target_balance``).

    The initial top-up uses ``_fund_to_target`` for both types, but targets
    the cap (``cap_balance``) for Capped budgets so the envelope starts full.

    Args:
        client:           Authenticated MibudgeClient.
        bank_account_id:  UUID of the bank account.
        target_budget:    Budget dict to backfill into.
        unallocated_id:   UUID of the account's Unallocated budget.
        funding_amount:   Per-period credit amount.  For Recurring, this is
                          ``target_balance`` (fill-to-target); for Capped
                          this is the fixed ``funding_amount`` field.
        budget_type:      ``'R'`` (Recurring) or ``'C'`` (Capped).
        cap_balance:      Hard ceiling for Capped budgets (their
                          ``target_balance``).  Ignored for Recurring.
        sched_str:        RFC 2445 recurrence string for the budget's
                          funding schedule (Capped budgets only).  When
                          parseable, transactions are grouped by the actual
                          firing dates rather than calendar months.
        yearly:           If True, group transactions by annual cycle.
        reset_month:      Month the annual cycle resets (ignored when not yearly).
        reset_day:        Day the annual cycle resets (ignored when not yearly).
        console:          Rich console.
        theme:            Rich theme.
    """
    # ----------------------------------------------------------------
    # 1. Fetch all transactions for the account, sorted chronologically.
    # ----------------------------------------------------------------
    console.print("[bold]Fetching all transactions…[/bold]")
    all_transactions: list[dict[str, Any]] = []
    with console.status("Loading transactions…"):
        all_transactions = list(
            client.get_all(
                "/api/v1/transactions/",
                {
                    "bank_account": bank_account_id,
                    "ordering": "transaction_date",
                },
                page_size=500,
            )
        )
    if not all_transactions:
        console.print(
            "[warning]No transactions found for this account.[/warning]"
        )
        return
    console.print(f"[dim]Loaded {len(all_transactions)} transaction(s).[/dim]")

    # ----------------------------------------------------------------
    # 2. Pre-fetch all allocations for this bank account.
    #    Build two indexes:
    #      unalloc_by_tx  : tx_id → alloc_id  (allocs to Unallocated)
    #      allocs_by_tx   : tx_id → list[alloc] (all allocs)
    # ----------------------------------------------------------------
    console.print("[bold]Fetching allocations…[/bold]")
    with console.status("Loading allocations…"):
        all_allocs: list[dict[str, Any]] = list(
            client.get_all(
                "/api/v1/allocations/",
                {"bank_account": bank_account_id},
                page_size=500,
            )
        )

    allocs_by_tx: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for alloc in all_allocs:
        tx_id = str(alloc["transaction"])
        allocs_by_tx[tx_id].append(alloc)

    # ----------------------------------------------------------------
    # 3. Group transactions by period.
    #    Capped budgets with a parseable funding_schedule are grouped by
    #    the actual schedule firing dates so that mid-month (or other
    #    sub-calendar) funding events are honoured.  All other budgets
    #    fall back to calendar-month or annual-cycle grouping.
    # ----------------------------------------------------------------
    use_schedule_dates = False
    funding_dates: list[date] = []
    period_label_map: dict[Any, str] = {}
    topup_label_map: dict[Any, str] = {}

    if budget_type == "C" and sched_str:
        first_date = _parse_tx_date(all_transactions[0]["transaction_date"])
        last_date = _parse_tx_date(all_transactions[-1]["transaction_date"])
        funding_dates = _enumerate_schedule_dates(
            sched_str, first_date, last_date
        )

    periods: dict[Any, list[dict[str, Any]]]

    if funding_dates:
        use_schedule_dates = True
        # Pre-create every period (including empty ones) so that top-ups
        # fire at every funding date, not just those with transactions.
        periods = {i: [] for i in range(len(funding_dates) + 1)}
        for tx in all_transactions:
            d = _parse_tx_date(tx["transaction_date"])
            periods[bisect.bisect_left(funding_dates, d)].append(tx)

        for i, fd in enumerate(funding_dates):
            prev = funding_dates[i - 1] if i > 0 else None
            start_str = (
                "start"
                if prev is None
                else (prev + timedelta(days=1)).strftime("%b %-d")
            )
            period_label_map[i] = f"{start_str} – {fd.strftime('%b %-d, %Y')}"
            topup_label_map[i] = f"{fd.strftime('%b %-d')} top-up — "
        last_p = len(funding_dates)
        period_label_map[last_p] = (
            f"{(funding_dates[-1] + timedelta(days=1)).strftime('%b %-d, %Y')}"
            " – present"
        )
    else:
        periods = defaultdict(list)
        for tx in all_transactions:
            d = _parse_tx_date(tx["transaction_date"])
            if yearly:
                key: Any = (_cycle_year_for_date(d, reset_month, reset_day),)
            else:
                key = (d.year, d.month)
            periods[key].append(tx)

    sorted_periods = sorted(periods.keys())
    if not sorted_periods:
        console.print("[warning]No transactions to process.[/warning]")
        return

    # ----------------------------------------------------------------
    # 4. Load vendor auto-rules.
    # ----------------------------------------------------------------
    rules = _load_rules(target_budget["id"])
    always_alloc = sum(1 for v in rules.values() if v is True)
    always_skip = sum(1 for v in rules.values() if v is False)
    if rules:
        console.print(
            f"[dim]Loaded {always_alloc} always-allocate and "
            f"{always_skip} always-skip rule(s) for this budget.[/dim]"
        )

    # ----------------------------------------------------------------
    # 5. Initial funding: top up the budget before the first month.
    #    Recurring: fill to target_balance (== funding_amount for recurring).
    #    Capped: fill to cap so the backfill starts from a full envelope.
    # ----------------------------------------------------------------
    console.print()
    initial_target = (
        cap_balance
        if (budget_type == "C" and cap_balance is not None)
        else funding_amount
    )
    _fund_to_target(
        client,
        target_budget,
        unallocated_id,
        bank_account_id,
        initial_target,
        console=console,
        label="Initial funding — ",
    )

    # ----------------------------------------------------------------
    # 6. Period-by-period loop.
    # ----------------------------------------------------------------
    total_allocated = 0
    total_auto = 0
    total_skipped = 0
    # Pre-populate skip set from saved rules so persistent skips take
    # effect immediately without prompting.
    skip_vendors: set[str] = {k for k, v in rules.items() if v is False}

    for period_idx, period_key in enumerate(sorted_periods):
        txs = periods[period_key]

        if use_schedule_dates:
            period_label: str = period_label_map.get(
                period_key, str(period_key)
            )
            topup_label = topup_label_map.get(period_key, "Top-up — ")
            py, pm = 1, 1
        elif yearly:
            cy = period_key[0]
            period_label = str(cy)
            topup_label = f"Year-end top-up ({cy}) — "
            py, pm = cy, 1
        else:
            year, month = period_key[0], period_key[1]
            period_label = f"{calendar.month_name[month]} {year}"
            topup_label = "Month-end top-up — "
            py, pm = year, month

        # Find candidates: exactly one allocation, and it's to Unallocated.
        candidates: list[tuple[dict[str, Any], str]] = []
        for tx in txs:
            tx_id = str(tx["id"])
            tx_allocs = allocs_by_tx.get(tx_id, [])
            if len(tx_allocs) != 1:
                # Zero allocs (unusual) or split transaction — skip.
                continue
            alloc = tx_allocs[0]
            budget_id = str(alloc.get("budget") or "")
            if budget_id != unallocated_id:
                # Already allocated to some other budget.
                continue
            candidates.append((tx, str(alloc["id"])))

        if not candidates:
            console.print(
                Rule(
                    f"[dim]{period_label} — no unallocated transactions[/dim]",
                    style="dim",
                )
            )
        else:
            allocated, skipped, auto_alloc, quit_requested = _process_month(
                py,
                pm,
                candidates,
                client,
                target_budget,
                rules,
                skip_vendors,
                console=console,
                theme=theme,
                period_label=period_label,
            )
            total_allocated += allocated
            total_auto += auto_alloc
            total_skipped += skipped

            # Save rules after each period so progress isn't lost.
            _save_rules(target_budget["id"], rules)

            if quit_requested:
                console.print(
                    "\n[warning]Quit requested. Saving rules…[/warning]"
                )
                _save_rules(target_budget["id"], rules)
                break

        # End-of-period top-up (skip for the last period).
        is_last_period = period_idx == len(sorted_periods) - 1
        if not is_last_period:
            if budget_type == "C":
                assert cap_balance is not None
                _fund_by_amount(
                    client,
                    target_budget,
                    unallocated_id,
                    bank_account_id,
                    funding_amount,
                    cap_balance,
                    console=console,
                    label=topup_label,
                )
            else:
                _fund_to_target(
                    client,
                    target_budget,
                    unallocated_id,
                    bank_account_id,
                    funding_amount,
                    console=console,
                    label=topup_label,
                )
        console.print()

    # ----------------------------------------------------------------
    # 7. Summary.
    # ----------------------------------------------------------------
    console.print(Rule("Summary", style=f"bold {theme.rule_style}"))
    table = Table(show_header=False)
    table.add_column("Metric", style="bold")
    table.add_column("Count", justify="right")
    table.add_row("Allocated (manual)", f"[success]{total_allocated}[/success]")
    table.add_row("Allocated (auto-rule)", f"[accent]{total_auto}[/accent]")
    table.add_row("Skipped", f"[dim]{total_skipped}[/dim]")
    console.print(table)
    if rules:
        n_alloc = sum(1 for v in rules.values() if v is True)
        n_skip = sum(1 for v in rules.values() if v is False)
        console.print(
            f"[dim]{n_alloc} always-allocate, {n_skip} always-skip "
            f"rule(s) saved to {_RULES_PATH}[/dim]"
        )


########################################################################
########################################################################
#
@click.command(
    context_settings={"auto_envvar_prefix": "MIBUDGE"},
    help=(
        "Backfill transaction history for a recurring budget, month by month.\n\n"
        "For each unallocated transaction the script prompts: y / n / a(lways) / "
        "s(kip vendor) / q(uit). At the start and end of each month the budget is "
        "automatically topped up to its configured funding amount from Unallocated."
    ),
)
@click.option(
    "--url",
    "-u",
    default=None,
    help="Base URL of the mibudge API.  [default: https://localhost:8000]",
)
@click.option("--username", default=None, help="API username.")
@click.option(
    "--password",
    default=None,
    help="API password (prefer env var over CLI flag).",
)
@click.option(
    "--vault-path",
    default=None,
    help="Vault KV2 path for credentials (e.g. 'mibudge/importer').",
)
@click.option(
    "--ca-bundle",
    default=None,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to a PEM CA bundle to trust (overrides system CAs).",
)
@click.option(
    "--trust-local-certs",
    is_flag=True,
    help=(
        "Trust the mkcert root CA (located via `mkcert -CAROOT`). "
        "Required when connecting to a local dev server using mkcert TLS."
    ),
)
@click.option(
    "--account",
    "-a",
    required=True,
    help=(
        "Bank account — a UUID, name, or account number.  "
        "Must match exactly one account."
    ),
)
@click.option(
    "--budget",
    "-b",
    required=True,
    help=(
        "Recurring budget to backfill — a UUID or name fragment.  "
        "Must match exactly one budget in the account."
    ),
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Enable verbose (DEBUG) logging.",
)
@click.option(
    "--plain",
    is_flag=True,
    help="Disable rich output (auto-disabled when not a TTY).",
)
@theme_option
def cli_cmd(
    url: str | None,
    username: str | None,
    password: str | None,
    vault_path: str | None,
    ca_bundle: Path | None,
    trust_local_certs: bool,
    account: str,
    budget: str,
    verbose: bool,
    plain: bool,
    theme_name: str,
) -> None:
    """CLI entry point for the budget backfill tool."""
    theme = get_theme(theme_name)
    console = Console(theme=theme.rich, stderr=False)
    interactive = console.is_terminal and not plain
    _setup_logging(verbose, interactive, console=console)

    try:
        with _build_client(
            url=url,
            username=username,
            password=password,
            vault_path=vault_path,
            ca_bundle=ca_bundle,
            trust_local_certs=trust_local_certs,
            console=console,
            interactive=interactive,
        ) as client:
            # --- Authenticate ---
            if interactive:
                with console.status("[bold]Authenticating…"):
                    client.authenticate()
                console.print("[success]Authenticated.[/success]")
            else:
                client.authenticate()

            # --- Resolve bank account ---
            bank_account_id = _resolve_account_by_query(
                client, account, console=console, interactive=interactive
            )
            bank_account = client.get(
                f"/api/v1/bank-accounts/{bank_account_id}/"
            )
            unallocated_id: str | None = bank_account.get("unallocated_budget")
            if not unallocated_id:
                raise click.ClickException(
                    "This bank account has no Unallocated budget. "
                    "Cannot proceed with backfill."
                )

            # --- Resolve target budget ---
            target_budget = _resolve_budget(
                client, bank_account_id, budget, console=console
            )

            # --- Validate budget type ---
            budget_type = target_budget.get("budget_type", "")
            if budget_type not in ("R", "C"):
                raise click.ClickException(
                    f"Budget '{target_budget['name']}' has type {budget_type!r}. "
                    "Only Recurring (R) and Capped (C) budgets are supported."
                )

            # --- Detect period frequency ---
            # Recurring uses recurrance_schedule; Capped uses funding_schedule.
            if budget_type == "C":
                sched_str: str | None = target_budget.get("funding_schedule")
            else:
                sched_str = target_budget.get("recurrance_schedule")
            freq, dtstart = _parse_recurrance_schedule(sched_str)
            yearly = freq == "YEARLY"
            reset_month = dtstart.month if dtstart else 1
            reset_day = dtstart.day if dtstart else 1

            # --- Determine funding amounts ---
            if budget_type == "C":
                # Per-period credit: funding_amount field.
                # Hard ceiling:      target_balance field.
                raw_funding = target_budget.get("funding_amount")
                if raw_funding is None:
                    raise click.ClickException(
                        f"Budget '{target_budget['name']}' has no "
                        "funding_amount set."
                    )
                funding_amount = Decimal(str(raw_funding)).quantize(
                    Decimal("0.01")
                )
                if funding_amount <= 0:
                    raise click.ClickException(
                        f"Budget '{target_budget['name']}' funding_amount is "
                        f"{funding_amount}. Must be positive."
                    )
                raw_cap = target_budget.get("target_balance")
                if raw_cap is None:
                    raise click.ClickException(
                        f"Budget '{target_budget['name']}' has no "
                        "target_balance set."
                    )
                cap_balance: Decimal | None = Decimal(str(raw_cap)).quantize(
                    Decimal("0.01")
                )
                if cap_balance <= 0:
                    raise click.ClickException(
                        f"Budget '{target_budget['name']}' target_balance is "
                        f"{cap_balance}. Must be positive."
                    )
            else:
                # Recurring: fill to target_balance each period.
                raw_funding = target_budget.get("target_balance")
                if raw_funding is None:
                    raise click.ClickException(
                        f"Budget '{target_budget['name']}' has no "
                        "target_balance set."
                    )
                funding_amount = Decimal(str(raw_funding)).quantize(
                    Decimal("0.01")
                )
                if funding_amount <= 0:
                    raise click.ClickException(
                        f"Budget '{target_budget['name']}' target_balance is "
                        f"{funding_amount}. Must be positive."
                    )
                cap_balance = None

            if yearly:
                period_desc = "Annual"
                reset_label = (
                    f"\n[bold]Annual reset date:[/bold]      "
                    f"{reset_month:02d}/{reset_day:02d}"
                )
            else:
                period_desc = "Monthly"
                reset_label = ""

            if budget_type == "C":
                amounts_label = (
                    f"[bold]{period_desc} funding amount:[/bold]   "
                    f"{funding_amount}\n"
                    f"[bold]Cap (target_balance):[/bold]    {cap_balance}"
                )
            else:
                amounts_label = (
                    f"[bold]{period_desc} target (target_balance):[/bold] "
                    f"{funding_amount}"
                )

            console.print(
                Panel(
                    f"[bold]Account:[/bold] {bank_account.get('name', bank_account_id)}\n"
                    f"[bold]Budget:[/bold]  {target_budget['name']}\n"
                    f"{amounts_label}"
                    f"{reset_label}\n"
                    f"[bold]Rules file:[/bold] {_RULES_PATH}",
                    title="Backfill Configuration",
                    border_style=theme.border_style,
                )
            )

            _run_backfill(
                client,
                bank_account_id,
                target_budget,
                unallocated_id,
                funding_amount,
                budget_type=budget_type,
                cap_balance=cap_balance,
                sched_str=sched_str,
                yearly=yearly,
                reset_month=reset_month,
                reset_day=reset_day,
                console=console,
                theme=theme,
            )

    except AuthenticationError as e:
        raise click.ClickException(str(e)) from e
    except KeyboardInterrupt as e:
        raise click.Abort() from e


########################################################################
########################################################################
#
def cli() -> None:
    """Load .env and invoke the CLI."""
    load_dotenv()
    cli_cmd()


if __name__ == "__main__":
    cli()
