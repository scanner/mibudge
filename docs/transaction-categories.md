# Transaction Categories -- Implementation Reference

This document describes how mibudge models transaction categories, how a
transaction or split gets a category, and how categories from external
providers (bank scrapers, importers) are mapped onto ours.  It is written
for contributors; every claim is tied to a specific file and function.

---

## 1. Overview

A **transaction category** answers "what was this spent on?" -- e.g.
`Food & Drink : Groceries`.  Categories are a flat, two-part taxonomy:

- **group** -- the top-level bucket (`Food & Drink`).
- **name** -- the leaf (`Groceries`).

There is no parent/child nesting. Every row is a leaf; "group-level"
questions are answered with a `category__group` filter, not a separate
group object. A provider's single-level category (`Travel : Travel`)
maps to a row whose group equals its name.

The model is `TransactionCategory` in `app/moneypools/models.py`. It
replaced a 151-member `TextChoices` enum -- categories needed to be
shared, user-extensible, and queryable, which an enum cannot be.

Key rules:

- **`full_name`** is a derived property, `f"{group} : {name}"` (note the
  spaced ` : ` separator). There is no stored `full_name` column; the
  two columns are the source of truth.
- **NULL means unassigned.** A `Transaction.category` or
  `TransactionAllocation.category` of `NULL` is the "no category yet"
  state. There is no sentinel row -- the old `Uncategorized:Unassigned`
  placeholder was removed. (`Uncategorized : Unknown` survives as a real
  category for genuinely unknowable spend.)
- **Case-insensitive uniqueness** on `(group, name)`, enforced by two
  partial unique constraints: one across all global rows, one per owner
  (`transaction_category_unique_global` and
  `transaction_category_unique_per_owner`). Application code normalizes
  before writing (see §4).

---

## 2. Global vs. owned categories, and visibility

Every category has an `owner` FK to a user, which may be `NULL`:

- **Global categories** (`owner IS NULL`) -- the shared base set, seeded
  by migration `0038_seed_global_categories` (150 rows) and managed
  through the django-admin. Everyone sees them.
- **Custom categories** (`owner = <user>`) -- created by a user via the
  API. Visible to the owner and to anyone the owner shares a bank
  account with.

Visibility is computed per request by
`TransactionCategoryQuerySet.visible_to(user)`
(`app/moneypools/models.py`). A category is visible when **any** of:

1. it is global (`owner IS NULL`), or
2. the user owns it, or
3. its owner co-owns at least one bank account with the user
   (`owner__bankaccount__owners=user`), or
4. it is still **referenced** by a transaction or allocation on an
   account the user owns
   (`transactions__bank_account__owners=user` /
   `allocations__transaction__bank_account__owners=user`).

Clause 4 is the **grandfather** rule: if you shared an account, the
co-owner categorized some transactions with a custom category, and then
you stopped sharing, those transactions stay readable. This needs no
tombstones or snapshots -- the reverse join through the referencing rows
keeps a used category visible for exactly as long as it is used.

The API viewset (`TransactionCategoryViewSet`) applies `visible_to` in
`get_queryset()`, so list/retrieve/filters all operate on the visible
set automatically.

---

## 3. Where a category lives: Transaction *and* Allocation

A category is stored in **two** places, on purpose:

- **`Transaction.category`** -- the transaction's overall category,
  seeded from the provider hint and user-editable.
- **`TransactionAllocation.category`** -- the category of one portion of
  the transaction.

Both are nullable FKs with `on_delete=SET_NULL` (a DB-level safety net;
the API refuses to delete a referenced category -- see §6).

Why both? A single purchase can be split across budgets with different
categories -- a Costco run that is part `Groceries`, part `Home
Supplies`. The per-portion category lives on the allocation; the
transaction keeps the single "headline" category. **Multiple categories
per transaction = multiple allocations. There is no M2M anywhere.**

### The copy hook (one direction, once)

When an allocation is created, it **copies the transaction's current
category** unless the caller supplies one. This is the single hook, in
`app/moneypools/service/transaction_allocation.py::create()`:

```python
kwargs.setdefault("category", transaction.category)
```

This copy happens **only at allocation-creation time**. Edits never
propagate afterward, in either direction: changing the transaction's
category does not rewrite its allocations, and changing an allocation's
category does not touch the transaction. They are independent after the
initial copy.

---

## 4. Provider category mapping

External providers (the BofA scraper, importers, export files) supply
category hints in **their own vocabulary**, not ours. BofA says
`Groceries : Groceries` and `Shopping & Entertainment : General
Merchandise`; we say `Food & Drink : Groceries` and
`Uncategorized : Other Shopping`. The resolver bridges the two.

All resolution lives in `app/moneypools/service/categories.py`.

### Normalization

`normalize_category(raw)` turns any raw string into a `(group, name)`
pair: **split on the first colon**, strip each side, collapse internal
whitespace. A string with no colon becomes `group == name`. This is why
`Education: Tuition & Fees` (a real typo in the old data) and
`Education : Tuition & Fees` both resolve to the same row.

`alias_key(group, name)` builds the casefolded `"group:name"` lookup key
used by the alias table.

### The alias table

`TransactionCategoryAlias` (`provider`, `alias_key`, `category` FK,
unique per provider) is a persistent, admin-editable mapping from a
normalized provider string to one of our categories. It is the
authoritative override: a reviewed mapping (or an admin correction of a
bad auto-mapping) always wins, and takes effect on the next import
without touching any transaction data.

### Resolution order

`resolve_provider_category(provider, raw)` runs, in order:

1. **Alias lookup** on `(provider, alias_key)` -- if present, use it.
   This is FIRST so reviewed/corrected mappings always win.
2. **Exact full-name match** on global rows (case-insensitive on both
   group and name).
3. **Unique sub-name match** on global rows -- but **guarded**: only when
   the name is not *also* an existing global group name. Without the
   guard, BofA's single-level `Travel : Travel` would sub-name match
   `Business : Travel` instead of creating the intended top-level
   `Travel : Travel`.
4. **Auto-create** a global row for the normalized pair.

Every successful non-alias resolution (steps 2–4) **writes an alias
row**, so an auto-mapping that turns out wrong can be re-pointed in the
admin later. `resolve_category_string(raw)` is the non-alias core (steps
2–4) and is used directly by `import_bank_account` for portable
full-name strings.

> The dry-run mirror of these rules lives in
> `importers/harvest_bofa_categories.py::dry_run_resolve` so the harvest
> host can preview mappings without a DB. Keep the two in sync when the
> resolution order changes.

### Seeding aliases from a provider

Because a provider's vocabulary is discovered empirically and evolves,
the alias table is populated by a **management command, not a
migration**:

1. `importers/harvest_bofa_categories.py` scrapes the provider's
   category strings from real transactions and writes a review YAML with
   a proposed mapping and confidence for each (see
   [docs/importers.md](importers.md)).
2. A human reviews and edits the proposed `category:` targets.
3. `manage.py seed_category_aliases reviewed.yaml` upserts the alias
   rows idempotently, creating any missing target categories as global
   rows (see [docs/management-commands.md](management-commands.md)).

The committed seed file should contain only `provider` / `alias_key` /
`category` -- never the `samples:` the harvester emits, which carry raw
transaction descriptions (PII).

---

## 5. `Budget.auto_spend`

`Budget.auto_spend` is a `JSONField` holding a list of matcher strings.
When a new spend matches one of a budget's entries, it can be
auto-routed to that budget (the full auto-allocation-rules feature is
future work).

Entries are currently **transaction-category full names** in canonical
`{group} : {name}` form. They are stored as **strings, not category
UUIDs**, deliberately: an export/import must stay portable across
deployments, and category UUIDs are not stable between them.

`BudgetSerializer.validate_auto_spend`
(`app/moneypools/api/v1/serializers.py`) validates each entry against the
categories visible to the requester and rewrites it to the matched
category's canonical full name.

The string form intentionally leaves room for **other matcher kinds**
without a schema change -- e.g. a future `tag:groceries` entry matching
merchants tagged `#groceries`, once merchants and tags exist (see §7).
Keep the field loose until the auto-allocation-rules feature formalizes
it.

---

## 6. API surface

`TransactionCategoryViewSet` (`/api/v1/transaction-categories/`):

- **list / retrieve** -- the visible set (§2). Filters: `group`,
  `archived`, `scope` (`global` | `mine` | `shared`); search over group
  and name.
- **create** -- owner is forced to the requesting user; global rows are
  admin-only. Case-insensitive duplicates of a global or own category
  are rejected.
- **update / delete** -- owner-only. Deleting a category that is still
  referenced by any transaction or allocation returns **409** and points
  at archiving instead.
- **`archive` action** -- sets `archived=True` (hidden from pickers,
  existing references stay valid), mirroring `BudgetViewSet.archive`.

On `Transaction` and `TransactionAllocation` serializers, `category` is
the category UUID (a `SlugRelatedField(id)`), writable and
visibility-checked, with a read-only `category_full_name` for display.
Filters: `TransactionFilter` and `TransactionAllocationFilter` gained
`category` (UUID), `category_group`, and `uncategorized` (isnull).

> **Breaking change:** the allocation `category` filter param changed
> from the old enum string to the category UUID.

---

## 7. Future direction: merchants as first-class objects

Scraping per-transaction detail from providers is expensive and fragile
-- BofA rate-limits the detail dialog hard and changes its DOM. The
intended longer-term answer is to make **merchants** first-class Django
objects and drive categorization from the merchant, not the provider:

- A `Merchant` model, with transactions mapped to a merchant by matching
  the description / normalized name (the `merchant_signature` idea in the
  harvester is an early sketch of that matching).
- A merchant carries a default category. When a transaction is matched
  to a known merchant, we set the transaction's category from the
  merchant association -- no provider round-trip required.
- A merchant also carries its **Merchant Category Code (MCC)** -- the
  ISO 18245 4-digit code -- resolved via the `iso18245` Python package
  (now a main dependency; the transaction-details enrichment already
  stores per-transaction MCCs under exactly this warn-only policy) to a
  human-readable description. MCC is a second
  identity signal: it can seed or corroborate a merchant's default
  category (e.g. MCC `5411` → grocery), and it gives the future
  auto-allocation rules a stable, provider-independent thing to match on.
  Where a provider supplies an MCC on a transaction (BofA does, on the
  detail dialog), we store the raw 4-digit code and use `iso18245` only
  to look up / warn -- the package lags the registry, so an unknown code
  is still stored, never rejected.
- Merchant **tags** (`#groceries`) feeding `auto_spend` matchers
  (`tag:groceries`, §5), so budgets can target categories of merchants
  rather than enumerating categories.

In that world, provider category hints become a **bootstrap and a
fallback**: useful for seeding a new merchant's default category, but not
the primary path. The alias table and resolver described here remain the
mechanism for turning whatever hint we *do* get into one of our
categories; the merchant layer sits on top, deciding a category from
identity when a provider hint is missing or not worth fetching.

Related future work -- budget auto-allocation rules -- will match on
merchant name / transaction category / merchant category code (MCC), so
those columns are kept queryable as they are added. MCC is stored as the
raw 4-digit code (indexed) and interpreted through the `iso18245`
package, so rules can match a code directly or a category derived from
it.
