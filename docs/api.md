# mibudge API

Version 1.0.0.

REST API for the mibudge personal budgeting service.  Every versioned
endpoint is under `/api/v1/`; the token endpoints are under `/api/token/`.

## Authentication

Send one of:

- **Access token** -- `Authorization: Bearer <access>`.  The browser app
  gets a short-lived access token from `POST /api/token/` (email and
  password), which also sets the refresh token as an httpOnly cookie;
  `POST /api/token/refresh/` exchanges that cookie for a new access token
  and `POST /api/token/logout/` revokes it.
- **API key** -- `Authorization: Api-Key <key>`, for importers and other
  services.  Create keys at `/api/v1/users/me/api-keys/`; the key is shown
  once.  API keys reach the budgeting endpoints and can read
  `GET /api/v1/users/me/` (importers read `timezone`), but not the other
  user and security endpoints (profile updates, password and email
  change, invitations, API-key management), which answer 403.

A few endpoints need no credentials (the public invitation and
email-change link endpoints).  A bad credential is refused with 401 even
there.

## Permissions

- **Banks** and **currencies**: read-only, any authenticated caller.
- **Users**: list, retrieve and update are staff-only;
  `/api/v1/users/me/` is every caller's own profile.
- **Everything else** (bank accounts, budgets, transactions, allocations,
  internal transactions, categories): scoped to bank-account ownership.  A
  caller sees only the bank accounts they own and the objects in them;
  another bank account's objects answer 404.  Staff status does not bypass this.

## Money

A money value is a decimal string plus a sibling currency code: `"amount":
"-45.99"` with `"amount_currency": "USD"` (ISO 4217).  Debits are
negative.  Every amount is in its bank account's currency: in a request
the `<field>_currency` key is optional and defaults to the bank
account's, and any other currency is refused with 400 on that key.  A
new bank account takes its bank's default currency unless `currency` is
given.

## Pagination

List endpoints answer a page:

```json
{"count": 250, "next": "https://.../?page=3", "previous": "https://.../?page=1", "results": [...]}
```

`page` selects the page (a page past the end answers 404) and `page_size`
the number of results, 100 by default and at most 500.  Follow `next` until it is `null`.

## Throttling

Requests are rate-limited per caller:

- **Authenticated** (access token or API key): 20000/hour per user.  All of a user's API keys and sessions share the one budget.
- **Anonymous** (login and the public endpoints): 100/hour per client address.
- **Login** (`POST /api/token/`), on top of the anonymous limit: 10/min per client address, and 20/hour per email address.  A browser that has signed in to that email before carries a device cookie, and its attempts count against a separate 20/hour instead of the per-email limit.
- **Token refresh** (`POST /api/token/refresh/`): 60/min per client address.
- **Password change**: 10/hour per user, on top of the authenticated limit.

Over the limit a request answers 429 with a `Retry-After` header giving
the seconds to wait.  A throttled request was refused before it ran, so
it is safe to retry.  To pace a client:

- On 429, wait `Retry-After` seconds, then retry the same request.
- Without a `Retry-After`, back off exponentially with jitter (1s, 2s,
  4s, ... capped at a few minutes) instead of retrying at once.
- Some endpoints refuse with 429 for their own business limits (e.g.
  too many invitations to one address); the endpoint says so, and
  retrying soon will not succeed.
- Bulk work (imports) should send requests one at a time rather than in
  parallel, and spread a large batch over time rather than bursting it.

## Errors

An error body is `Error` or, for invalid input, `ValidationError`:

- `Error`: `{"detail": "..."}`, sometimes with a machine-readable
  `"code"` as well (e.g. `"token_not_valid"` from the token endpoints).
- `ValidationError`: a map of field name to messages, with
  `non_field_errors` for errors not tied to one field:

  ```json
  {"target_balance": ["This field is required."], "non_field_errors": ["..."]}
  ```

  A field's messages may be a single string instead of a list, a list of
  per-item maps for a list field, or a nested map.  Some actions answer a
  bare list of messages instead, e.g. `["Cannot split a pending
  transaction."]`.

The statuses every endpoint of a kind shares are described once, under
Common responses; each endpoint lists which apply to it, and its own
errors in full.

## Common responses

Error statuses shared by every endpoint of a kind.  Each endpoint lists the ones that apply to it.

| Status | Body | Meaning |
|---|---|---|
| `400` | ValidationError | Invalid input: a field error in the request body, or a bad filter value on a list. |
| `401` | Error | Missing, invalid or expired credentials.  Sent even to public endpoints when a bad credential is given. |
| `403` | Error | The credentials may not use this endpoint: it is staff-only, or it needs an interactive login and got an API key. |
| `404` | Error | No such object, or one the caller cannot see. |
| `404` | Error | The requested `page` is past the last one. |
| `429` | Error | Rate limit exceeded; wait `Retry-After` seconds (see Throttling). |

## Endpoints

### auth

#### `POST /api/token/`

JWT obtain endpoint that stores the refresh token in an httpOnly
cookie and returns only the access token in the response body.

This is the browser-SPA login flow: JS receives the short-lived
access token (kept in memory); the refresh token is a
Secure/HttpOnly/SameSite=Strict cookie that JS cannot read,
and that the browser sends automatically to /api/token/refresh/.

A successful login also sets a login device cookie, so this
browser's later attempts against the same email count against a
limit of their own instead of the per-email one.

Send:

```jsonc
{
  "email": "string",                // string · required
  "password": "string"              // string · required
}
```

**200**

Returns [AccessToken](#accesstoken-object).

Errors:

- **401** (Error) -- Wrong email or password.

Common responses: `400` · `429`

#### `POST /api/token/logout/`

Sign-out endpoint: blacklists the refresh token in the httpOnly
cookie and expires the cookie, so a reload cannot sign the user
back in.

Always answers 204.  A missing, invalid, expired or already
blacklisted cookie leaves nothing to revoke, and the cookie is
cleared either way.

**204** -- no body.

Common responses: `429`

#### `POST /api/token/refresh/`

JWT refresh endpoint that reads the refresh token from the httpOnly
cookie rather than the request body.

On success, returns {"access": "<new_access_token>"} in JSON.
When token rotation is enabled, also rotates the refresh cookie so
the 14-day sliding window resets with each use.

Refreshes have their own per-address limit in place of the
anonymous one, so page loads and sign-in attempts do not share a
budget.

**200**

Returns [AccessToken](#accesstoken-object).

Errors:

- **401** (Error) -- No refresh cookie, or its token is invalid or expired.

Common responses: `429`

#### AccessToken object

```jsonc
{
  "access": "string"                // string
}
```

### allocations

#### `GET /api/v1/allocations/`

**List transaction allocations.**

Return allocations belonging to the authenticated user's transactions. Filterable by transaction, budget, and category. Orderable by created_at.

| Parameter | In | Type | | Description |
|---|---|---|---|---|
| `bank_account` | query | uuid |  |  |
| `budget` | query | uuid |  |  |
| `category` | query | uuid |  |  |
| `category_group` | query | string |  |  |
| `ordering` | query | string |  | Which field to use when ordering the results. |
| `transaction` | query | uuid |  |  |
| `uncategorized` | query | boolean |  |  |

**200**

Returns a page of [TransactionAllocation](#transactionallocation-object) (see Pagination).

Common responses: `400` · `401` · `404` · `429`

#### `GET /api/v1/allocations/{id}/`

**Get allocation details.**

Return a single transaction allocation by UUID.

**200**

Returns [TransactionAllocation](#transactionallocation-object).

Common responses: `401` · `404` · `429`

#### TransactionAllocation object

```jsonc
{
  "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",  // uuid · read-only
  "transaction": "3fa85f64-5717-4562-b3fc-2c963f66afa6",  // uuid · required
  "budget": "3fa85f64-5717-4562-b3fc-2c963f66afa6",  // uuid | null · optional
  "amount": "125.00",               // decimal · required
  // ISO 4217 currency of `amount`. Optional: defaults to the bank account's currency,
  // and any other currency is refused.
  "amount_currency": "USD",         // string · optional
  "budget_balance": "125.00",       // decimal · read-only
  "budget_balance_currency": "USD",  // string · read-only
  "category": "3fa85f64-5717-4562-b3fc-2c963f66afa6",  // uuid | null · optional
  "category_full_name": "string",   // string | null · read-only
  "memo": "string",                 // string | null · optional
  "created_at": "2026-09-29T14:00:00Z",  // date-time · read-only
  "modified_at": "2026-09-29T14:00:00Z"  // date-time · read-only
}
```

### bank-accounts

#### `GET /api/v1/bank-accounts/`

**List bank accounts.**

Return bank accounts owned by the authenticated user. Filterable by account_type. Orderable by name or created_at.

| Parameter | In | Type | | Description |
|---|---|---|---|---|
| `account_type` | query | enum |  | `C` Checking, `S` Savings, `X` Credit Card |
| `ordering` | query | string |  | Which field to use when ordering the results. |

**200**

Returns a page of [BankAccount](#bankaccount-object) (see Pagination).

Common responses: `400` · `401` · `404` · `429`

#### `POST /api/v1/bank-accounts/`

**Create a bank account.**

Create a new bank account. The authenticated user is automatically added as an owner. An 'Unallocated' budget is auto-created by a post_save signal. Optionally set initial posted_balance, available_balance, and currency (all immutable after creation).

Send [BankAccount](#bankaccount-object) -- its writable fields.

**201**

Returns [BankAccount](#bankaccount-object).

Common responses: `400` · `401` · `429`

#### `GET /api/v1/bank-accounts/{id}/`

**Get bank account details.**

Return a single bank account by UUID.

**200**

Returns [BankAccount](#bankaccount-object).

Common responses: `401` · `404` · `429`

#### `PUT /api/v1/bank-accounts/{id}/`

**Update a bank account.**

Full update of a bank account. Only 'name' is mutable after creation -- bank, account_type, currency, and balances are rejected if changed.

Send [BankAccount](#bankaccount-object) -- its writable fields.

**200**

Returns [BankAccount](#bankaccount-object).

Common responses: `400` · `401` · `404` · `429`

#### `PATCH /api/v1/bank-accounts/{id}/`

**Partially update a bank account.**

Partial update of a bank account. Only 'name' is mutable after creation.

Send [BankAccount](#bankaccount-object) -- any subset of its writable fields.

**200**

Returns [BankAccount](#bankaccount-object).

Common responses: `400` · `401` · `404` · `429`

#### `DELETE /api/v1/bank-accounts/{id}/`

**Delete a bank account.**

Delete a bank account and all associated budgets, transactions, and allocations. Requires an interactive login session; API keys get 403.

**204** -- no body.

Common responses: `401` · `403` · `404` · `429`

#### `GET /api/v1/bank-accounts/{id}/funding-event-dates/`

**Funding event dates.**

Return all dates in (after, before] on which at least one funding or recurrence event is due for this account.  The importer uses this to find batch-split boundaries.

| Parameter | In | Type | | Description |
|---|---|---|---|---|
| `after` | query | date | required | Exclusive lower bound (YYYY-MM-DD). |
| `before` | query | date | required | Inclusive upper bound (YYYY-MM-DD). |

**200**

Returns:

```jsonc
{
  "dates": ["2026-09-29"]           // array of date
}
```

Errors:

- **400** (ValidationError) -- 'after' or 'before' is missing or not a date.

Common responses: `401` · `404` · `429`

#### `GET /api/v1/bank-accounts/{id}/funding-summary/`

**Funding summary.**

Return the total amounts that will be automatically funded at the next event for each distinct funding schedule on this account.  Only active, schedulable budgets are included -- paused, archived, completed goals, and RECURRING budgets that delegate to a fill-up goal are excluded.  Results are grouped by funding schedule (RRULE string) and sorted by next event date.

Example: The account after creating the Rent budget (see budgets_create).

**200**

Returns:

```jsonc
{
  "schedules": [{...}],             // array of FundingScheduleTotal
  "total_amount": "125.00",         // decimal
  "currency": "USD"                 // string
}
```

Nested objects: [FundingScheduleTotal](#fundingscheduletotal-object).

*Example response -- Rent's fill-up goal gets $900.00 on the 1st:*

```json
{
  "schedules": [
    {
      "schedule": "DTSTART:20261001T000000Z\nRRULE:FREQ=MONTHLY;BYMONTHDAY=1,15",
      "next_date": "2026-10-01",
      "total_amount": "900.00",
      "currency": "USD",
      "budget_count": 1
    }
  ],
  "total_amount": "900.00",
  "currency": "USD"
}
```

Common responses: `401` · `404` · `429`

#### `GET /api/v1/bank-accounts/{id}/invitations/`

**List pending invitations for this account.**

Returns all pending invitations for this bank account.

**200**

Returns an array of [BankAccountInvitation](#bankaccountinvitation-object).

Common responses: `401` · `403` · `404` · `429`

#### `POST /api/v1/bank-accounts/{id}/invitations/{token}/cancel/`

**Cancel a pending invitation.**

Cancel a pending co-ownership invitation by token. Only the user who sent the invitation may cancel it.

| Parameter | In | Type | | Description |
|---|---|---|---|---|
| `token` | path | string | required | The invitation's opaque token. |

**200** -- no body.

Errors:

- **400** (Error) -- The invitation is no longer pending.
- **403** (Error) -- Only the invitation's sender may cancel it, or the credentials are not interactive.
- **404** (Error) -- No such account or invitation.

Common responses: `401` · `429`

#### `POST /api/v1/bank-accounts/{id}/invite/`

**Invite a co-owner.**

Send a co-ownership invitation to the given email address. If no mibudge account exists for that address, an inactive placeholder account is created; the invitee sets their password after accepting. Returns 409 if the address is already an owner or a pending invitation already exists; 429 if too many invitations have been sent to this address for this account in the rolling window.

Send:

```jsonc
{
  "invitee_email": "user@example.com"  // email · required
}
```

**201** -- no body.

Errors:

- **409** (Error) -- The address is already an owner, or has a pending invitation.
- **429** (Error) -- Too many invitations to this address for this account.

Common responses: `400` · `401` · `403` · `404`

#### `POST /api/v1/bank-accounts/{id}/mark-imported/`

**Mark import complete.**

Record that a transaction import has been completed for this account.  Sets last_imported_at to now and advances last_posted_through to the supplied date (never regresses an existing value).  Body: {"last_posted_through": "YYYY-MM-DD"}.

Send:

```jsonc
{
  "last_posted_through": "2026-09-29"  // date · required
}
```

**200**

Returns [BankAccount](#bankaccount-object).

Common responses: `400` · `401` · `404` · `429`

#### `POST /api/v1/bank-accounts/{id}/run-funding/`

**Run funding.**

Run the funding engine for this account immediately.  Processes all due fund and recurrence events up to `as_of` (defaults to today) and returns a summary of what happened.  Pass `as_of` when calling between import batches so the engine only sees events up to that batch boundary date.

Example: Run funding for events due through 2026-09-30.

Send:

```jsonc
{
  // Upper bound for event enumeration (YYYY-MM-DD). Defaults to today.
  "as_of": "2026-09-29"             // date · optional
}
```

*Example request:*

```json
{
  "as_of": "2026-09-30"
}
```

**200**

Returns:

```jsonc
{
  "transfers": 0,                   // integer
  "occurrences_completed": 0,       // integer
  "occurrences_partial": 0,         // integer
  "warnings": ["string"],           // array of string
  // Names of paused budgets the run skipped.
  "skipped_budgets": ["string"]     // array of string
}
```

*Example response -- Two transfers made; a paused budget skipped:*

```json
{
  "transfers": 2,
  "occurrences_completed": 2,
  "occurrences_partial": 0,
  "warnings": [],
  "skipped_budgets": [
    "Vacation"
  ]
}
```

Errors:

- **409** (Error) -- Either another worker is currently processing this account (lock held), or there is nothing due or outstanding to run as of the supplied date.
- **503** (Error) -- The funding system user is not configured.

Common responses: `400` · `401` · `404` · `429`

#### `POST /api/v1/bank-accounts/{id}/sync-scrape/`

**Sync a bank-side scrape.**

Reconcile this account against a fresh snapshot from a live bank scraper.  All existing pending transactions on the account are deleted, posted transactions from the scrape are de-duplicated against the database, and any new posted/pending rows are inserted in the order the scraper supplies (newest-first).  Per-transaction running balance snapshots and the unallocated-budget allocation snapshots are recomputed before the request returns.  Runs atomically under the account + unallocated-budget locks; on any error the database is unchanged.

Example: One pending and one posted row, newest first.

On an account whose previous sync left one pending row and whose balance agrees with the bank's.  `details_needed[].index` points into the submitted `transactions` array; send those rows' details to `transaction-details`.

Send:

```jsonc
{
  "scraped_at": "2026-09-29T14:00:00Z",  // date-time · required
  "ending_balance": "125.00",       // decimal · required
  "transactions": [{...}],          // array of ScrapeSyncTransaction · required
  // ISO 4217 currency of `ending_balance`. Optional: defaults to the bank account's
  // currency, and any other currency is refused.
  "ending_balance_currency": "USD"  // string · optional
}
```

Nested objects: [ScrapeSyncTransaction](#scrapesynctransaction-object).

*Example request:*

```json
{
  "scraped_at": "2026-09-29T08:15:00-07:00",
  "ending_balance": "1432.18",
  "ending_balance_currency": "USD",
  "transactions": [
    {
      "is_pending": true,
      "posted_date": "2026-09-29T08:15:00-07:00",
      "raw_description": "CORNER MARKET 09/28 PURCHASE",
      "amount": "-18.25",
      "amount_currency": "USD",
      "transaction_type": "",
      "running_balance": null
    },
    {
      "is_pending": false,
      "posted_date": "2026-09-28T00:00:00-07:00",
      "raw_description": "BLUE BOTTLE COFFEE 09/27 PURCHASE",
      "amount": "-6.50",
      "amount_currency": "USD",
      "transaction_type": "signature_purchase",
      "running_balance": "1450.43"
    }
  ]
}
```

**200**

Returns:

```jsonc
{
  "deleted_pending": 0,             // integer
  "inserted_posted": 0,             // integer
  "skipped_posted": 0,              // integer
  "inserted_pending": 0,            // integer
  "balance_mismatch": "125.00",     // decimal | null
  "posting_order_mismatches": ["string"],  // array of string
  "last_posted_through": "2026-09-29",  // date | null
  "new_transaction_ids": ["3fa85f64-5717-4562-b3fc-2c963f66afa6"],  // array of uuid
  "details_needed": [{...}]         // array of ScrapeSyncDetailsNeeded
}
```

Nested objects: [ScrapeSyncDetailsNeeded](#scrapesyncdetailsneeded-object).

*Example response -- The pending row replaced, the posted row new and needing details:*

```json
{
  "deleted_pending": 1,
  "inserted_posted": 1,
  "skipped_posted": 0,
  "inserted_pending": 1,
  "balance_mismatch": null,
  "posting_order_mismatches": [],
  "last_posted_through": "2026-09-28",
  "new_transaction_ids": [
    "d3c2b1a0-9f8e-4d7c-8b6a-5f4e3d2c1b0a",
    "9a8b7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6e"
  ],
  "details_needed": [
    {
      "index": 1,
      "transaction": "d3c2b1a0-9f8e-4d7c-8b6a-5f4e3d2c1b0a"
    }
  ]
}
```

Common responses: `400` · `401` · `404` · `429`

#### `POST /api/v1/bank-accounts/{id}/transaction-details/`

**Apply scraped transaction details.**

Apply per-transaction detail records (merchant name, location, MCC, virtual card number) fetched by a live scraper to posted transactions on this account.  Each raw details dict is stored verbatim on its transaction and the merchant columns are extracted from it.  An item's optional `category` is a mibudge category full name ('{group} : {name}') -- importers translate their provider's category vocabulary before submitting.  It seeds the transaction's category (and its unassigned allocations) when NULL; an unknown name yields a per-item warning and leaves the transaction unassigned.  The display description is recomposed on first enrichment unless the user has edited it.  Rows already enriched are skipped unless `overwrite` is true; pending rows are always skipped.  Per-item outcomes are returned in submission order.

Example: Details for the row `sync-scrape` asked for.

`details` is the provider's raw record, stored verbatim; mibudge reads `merchant_name`, `merchant_information` ('CITY, ST'), `merchant_category`, `merchant_category_code` and `virtual_card_number` from it.  `category` is a mibudge category full name.

Send:

```jsonc
{
  "overwrite": false,               // boolean · optional
  "details": [{...}]                // array of TransactionDetailsItem · required
}
```

Nested objects: [TransactionDetailsItem](#transactiondetailsitem-object).

*Example request:*

```json
{
  "overwrite": false,
  "details": [
    {
      "transaction": "d3c2b1a0-9f8e-4d7c-8b6a-5f4e3d2c1b0a",
      "details": {
        "merchant_name": "Blue Bottle Coffee",
        "merchant_information": "OAKLAND, CA",
        "merchant_category": "Coffee Shops",
        "merchant_category_code": "5814"
      },
      "category": "Food & Drink : Coffee & Tea"
    }
  ]
}
```

**200**

Returns:

```jsonc
{
  "applied": 0,                     // integer
  "skipped_has_details": 0,         // integer
  "skipped_pending": 0,             // integer
  "not_found": 0,                   // integer
  "results": [{...}]                // array of TransactionDetailsResult
}
```

Nested objects: [TransactionDetailsResult](#transactiondetailsresult-object).

*Example response -- Applied, with nothing to warn about:*

```json
{
  "applied": 1,
  "skipped_has_details": 0,
  "skipped_pending": 0,
  "not_found": 0,
  "results": [
    {
      "transaction": "d3c2b1a0-9f8e-4d7c-8b6a-5f4e3d2c1b0a",
      "status": "applied",
      "warnings": []
    }
  ]
}
```

Common responses: `400` · `401` · `404` · `429`

#### BankAccount object

```jsonc
{
  "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",  // uuid · read-only
  "name": "string",                 // string · required
  "bank": "3fa85f64-5717-4562-b3fc-2c963f66afa6",  // uuid · required
  "owners": ["string"],             // array of string · read-only
  // "C" Checking, "S" Savings, "X" Credit Card
  "account_type": "C",              // enum · optional
  "account_number": "string",       // string | null · optional
  // ISO 4217 currency code (e.g. USD, EUR, GBP).
  "currency": "USD",                // string · optional
  "posted_balance": "125.00",       // decimal · optional
  // ISO 4217 currency of `posted_balance`. Optional: defaults to the bank account's
  // currency, and any other currency is refused.
  "posted_balance_currency": "USD",  // string · optional
  "available_balance": "125.00",    // decimal · optional
  // ISO 4217 currency of `available_balance`. Optional: defaults to the bank account's
  // currency, and any other currency is refused.
  "available_balance_currency": "USD",  // string · optional
  "unallocated_budget": "3fa85f64-5717-4562-b3fc-2c963f66afa6",  // uuid | null · read-only
  // When enabled (the default), scheduled funding and recurrence events run
  // automatically for this account. Disable to opt out of automation and drive funding
  // entirely from the 'Run funding now' button.
  "auto_funding_enabled": false,    // boolean · optional
  // Wall-clock time of the most recent completed import for this account.
  "last_imported_at": "2026-09-29T14:00:00Z",  // date-time | null · read-only
  // Latest posted_date seen in the most recent import batch. The funding engine will
  // not process events dated after this value.
  "last_posted_through": "2026-09-29",  // date | null · read-only
  "created_at": "2026-09-29T14:00:00Z",  // date-time · read-only
  "modified_at": "2026-09-29T14:00:00Z"  // date-time · read-only
}
```

#### BankAccountInvitation object

```jsonc
{
  "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",  // uuid
  "token": "string",                // string
  "bank_account_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",  // uuid
  "bank_account_name": "string",    // string
  // Email address the invitation was sent to. Immutable after creation.
  "invitee_email": "user@example.com",  // email
  "invited_by": "user@example.com",  // email
  // "pending" Pending, "accepted" Accepted, "declined" Declined, "cancelled" Cancelled,
  // "expired" Expired
  "status": "pending",              // enum
  "expires_at": "2026-09-29T14:00:00Z",  // date-time
  "accepted_at": "2026-09-29T14:00:00Z",  // date-time | null
  "declined_at": "2026-09-29T14:00:00Z",  // date-time | null
  "cancelled_at": "2026-09-29T14:00:00Z",  // date-time | null
  "created_at": "2026-09-29T14:00:00Z",  // date-time
  "modified_at": "2026-09-29T14:00:00Z"  // date-time
}
```

#### FundingScheduleTotal object

```jsonc
{
  "schedule": "string",             // string -- The RRULE string.
  "next_date": "2026-09-29",        // date
  "total_amount": "125.00",         // decimal
  "currency": "USD",                // string
  "budget_count": 0                 // integer
}
```

#### ScrapeSyncDetailsNeeded object

```jsonc
{
  "index": 0,                       // integer
  "transaction": "3fa85f64-5717-4562-b3fc-2c963f66afa6"  // uuid
}
```

#### ScrapeSyncTransaction object

```jsonc
{
  "is_pending": false,              // boolean · required
  "posted_date": "2026-09-29T14:00:00Z",  // date-time · required
  "raw_description": "string",      // string · required
  "amount": "125.00",               // decimal · required
  "transaction_type": "string",     // string · optional
  "running_balance": "125.00",      // decimal | null · optional
  // ISO 4217 currency of `amount`. Optional: defaults to the bank account's currency,
  // and any other currency is refused.
  "amount_currency": "USD"          // string · optional
}
```

#### TransactionDetailsItem object

```jsonc
{
  "transaction": "3fa85f64-5717-4562-b3fc-2c963f66afa6",  // uuid · required
  "details": {"<key>": null},       // map of any · required
  "category": "string"              // string | null · optional
}
```

#### TransactionDetailsResult object

```jsonc
{
  "transaction": "3fa85f64-5717-4562-b3fc-2c963f66afa6",  // uuid
  // "applied", "skipped_has_details", "skipped_pending", "not_found"
  "status": "applied",              // enum
  "warnings": ["string"]            // array of string
}
```

### banks

#### `GET /api/v1/banks/`

**List banks.**

Return all banks in the system. Banks are shared reference data managed through the admin -- any authenticated user can list and retrieve them.

| Parameter | In | Type | | Description |
|---|---|---|---|---|
| `ordering` | query | string |  | Which field to use when ordering the results. |

**200**

Returns a page of [Bank](#bank-object) (see Pagination).

Common responses: `401` · `404` · `429`

#### `GET /api/v1/banks/{id}/`

**Get bank details.**

Return a single bank by UUID.

**200**

Returns [Bank](#bank-object).

Common responses: `401` · `404` · `429`

#### Bank object

```jsonc
{
  "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",  // uuid
  "name": "string",                 // string
  "routing_number": "string",       // string | null
  // ISO 4217 currency code (e.g. USD, EUR, GBP).
  "default_currency": "USD",        // string
  "created_at": "2026-09-29T14:00:00Z",  // date-time
  "modified_at": "2026-09-29T14:00:00Z"  // date-time
}
```

### budgets

#### `GET /api/v1/budgets/`

**List budgets.**

Return budgets belonging to the authenticated user's accounts. Filterable by bank_account, budget_type, archived, and paused. Searchable by name. Orderable by name, created_at, or balance.

| Parameter | In | Type | | Description |
|---|---|---|---|---|
| `archived` | query | boolean |  |  |
| `bank_account` | query | uuid |  |  |
| `budget_type` | query | enum |  | `G` Goal, `R` Recurring, `A` Associated Fill-up Goal, `C` Capped |
| `ordering` | query | string |  | Which field to use when ordering the results. |
| `paused` | query | boolean |  |  |
| `search` | query | string |  | A search term. |

**200**

Returns a page of [Budget](#budget-object) (see Pagination).

Common responses: `400` · `401` · `404` · `429`

#### `POST /api/v1/budgets/`

**Create a budget.**

Create a new budget under a bank account. Required: name, bank_account (UUID), budget_type, funding_type, and target_balance. The bank_account and budget_type are immutable after creation. Balance is managed by signals and is always read-only.

Example: $1800 rent, refreshed on the 1st, funded on the 1st and 15th.

A Recurring budget also gets an associated fill-up goal (`fillup_goal` in the response). The funding schedule fills the goal toward `target_balance` by the next `recurrence_schedule` date, when its balance moves into the budget.

Send [Budget](#budget-object) -- its writable fields.

*Example request:*

```json
{
  "name": "Rent",
  "bank_account": "6f1c2a3e-8b4d-4e5f-9a1b-2c3d4e5f6a7b",
  "budget_type": "R",
  "funding_type": "D",
  "target_balance": "1800.00",
  "funding_schedule": "DTSTART:20261001T000000Z\nRRULE:FREQ=MONTHLY;BYMONTHDAY=1,15",
  "recurrence_schedule": "DTSTART:20261001T000000Z\nRRULE:FREQ=MONTHLY"
}
```

**201**

Returns [Budget](#budget-object).

Common responses: `400` · `401` · `429`

#### `GET /api/v1/budgets/{id}/`

**Get budget details.**

Return a single budget by UUID.

**200**

Returns [Budget](#budget-object).

Common responses: `401` · `404` · `429`

#### `PUT /api/v1/budgets/{id}/`

**Update a budget.**

Full update of a budget. bank_account and budget_type are immutable. The unallocated budget cannot be renamed.

Send [Budget](#budget-object) -- its writable fields.

**200**

Returns [BudgetUpdateResult](#budgetupdateresult-object).

Common responses: `400` · `401` · `404` · `429`

#### `PATCH /api/v1/budgets/{id}/`

**Partially update a budget.**

Partial update of a budget. bank_account and budget_type are immutable. The unallocated budget cannot be renamed.

Send [Budget](#budget-object) -- any subset of its writable fields.

**200**

Returns [BudgetUpdateResult](#budgetupdateresult-object).

Common responses: `400` · `401` · `404` · `429`

#### `DELETE /api/v1/budgets/{id}/`

**Delete a budget.**

Delete a budget and its fill-up goal. The unallocated budget cannot be deleted (403). A budget whose own or fill-up goal's transaction allocations exist cannot be deleted (400) -- archive it instead. Transfers between the deleted budgets and other budgets are reversed on those budgets, and any remaining balance moves to the unallocated budget.

**204** -- no body.

Errors:

- **400** (ValidationError) -- The budget has transaction allocations; archive it instead.
- **403** (Error) -- The unallocated budget cannot be deleted or archived.

Common responses: `401` · `404` · `429`

#### `POST /api/v1/budgets/{id}/archive/`

**Archive a budget.**

Archive a budget. Any remaining balance is transferred to the account's unallocated budget. If the budget has an associated fill-up goal, that budget is also archived and its balance moved to unallocated. The unallocated budget cannot be archived.

**200**

Returns [Budget](#budget-object).

Errors:

- **400** (ValidationError) -- The budget is already archived.
- **403** (Error) -- The unallocated budget cannot be deleted or archived.

Common responses: `401` · `404` · `429`

#### Budget object

```jsonc
{
  "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",  // uuid · read-only
  "name": "string",                 // string · required
  "bank_account": "3fa85f64-5717-4562-b3fc-2c963f66afa6",  // uuid · required
  "balance": "125.00",              // decimal · read-only
  "balance_currency": "USD",        // string · read-only
  // For Goal budgets: running net of all ITX credits minus debits. Unused for other
  // types.
  "funded_amount": "125.00",        // decimal · read-only
  "funded_amount_currency": "USD",  // string · read-only
  "target_balance": "125.00",       // decimal · required
  // ISO 4217 currency of `target_balance`. Optional: defaults to the bank account's
  // currency, and any other currency is refused.
  "target_balance_currency": "USD",  // string · optional
  "funding_amount": "125.00",       // decimal | null · optional
  // ISO 4217 currency of `funding_amount`. Optional: defaults to the bank account's
  // currency, and any other currency is refused.
  "funding_amount_currency": "USD",  // string | null · optional
  // "G" Goal, "R" Recurring, "A" Associated Fill-up Goal, "C" Capped
  "budget_type": "G",               // enum · optional
  // "D" Target Date, "F" Fixed Amount
  "funding_type": "D",              // enum · optional
  "target_date": "2026-09-29",      // date | null · optional
  "fillup_goal": "3fa85f64-5717-4562-b3fc-2c963f66afa6",  // uuid | null · read-only
  "archived": false,                // boolean · read-only
  "archived_at": "2026-09-29T14:00:00Z",  // date-time | null · read-only
  // True when this budget has reached its target and should not be funded further.
  // Managed by signals and funding tasks; do not set manually.
  "complete": false,                // boolean · read-only
  // A paused budget does not get automatically funded on its schedule.
  "paused": false,                  // boolean · optional
  "funding_schedule": "string",     // string · optional
  // Refresh cycle for Recurring budgets. Restricted grammar: a single RRULE whose FREQ
  // is WEEKLY, MONTHLY, or YEARLY with an optional INTERVAL, plus an optional DTSTART
  // that anchors the day the cycle refreshes on (e.g. 'DTSTART:20260708T000000Z
  // RRULE:FREQ=MONTHLY' refreshes on the 8th of every month). BY* parts, COUNT, UNTIL,
  // and exception rules/dates are rejected -- the anchor date is the only day-of-cycle
  // control. The funding_schedule field is not restricted this way.
  "recurrence_schedule": "string",  // string | null · optional
  "memo": "string",                 // string | null · optional
  // Transaction-category full names ('{group} : {name}'). Spend in a listed category is
  // auto-routed to this budget.
  "auto_spend": ["string"],         // array of string · optional
  "next_funding": {...},            // NextFunding | null · read-only
  "next_recurrence": "2026-09-29",  // date | null · read-only
  // "ahead", "on_track", "behind"
  "funding_pace": "ahead",          // enum | null · read-only
  "created_at": "2026-09-29T14:00:00Z",  // date-time · read-only
  "modified_at": "2026-09-29T14:00:00Z"  // date-time · read-only
}
```

Nested objects: [NextFunding](#nextfunding-object).

#### BudgetUpdateResult object

Every field of [Budget](#budget-object), plus:

```jsonc
{
  "warnings": ["string"]            // array of string
}
```

#### NextFunding object

```jsonc
{
  "date": "2026-09-29",             // date
  "amount": "125.00",               // decimal
  "amount_currency": "USD"          // string
}
```

### channel-preferences

#### `GET /api/v1/channel-preferences/`

**List channel preferences.**

Return all notification channels with the authenticated user's delivery preferences. Channels without a stored preference fall back to DAILY_MORNING.

**200**

Returns an array of [ChannelPreference](#channelpreference-object).

Common responses: `401` · `429`

#### `PATCH /api/v1/channel-preferences/{channel}/`

**Update a channel preference.**

Set the digest_frequency for a notification channel. Returns 404 if the channel value is not valid.

| Parameter | In | Type | | Description |
|---|---|---|---|---|
| `channel` | path | string | required | Channel identifier (e.g. 'email'). |

Send [ChannelPreference](#channelpreference-object) -- any subset of its writable fields.

**200**

Returns [ChannelPreference](#channelpreference-object).

Common responses: `400` · `401` · `404` · `429`

#### ChannelPreference object

```jsonc
{
  "channel": "string",              // string
  "display_name": "string",         // string
  // "daily_morning" Once daily (morning, ~7 am), "daily_evening" Once daily (evening,
  // ~6 pm), "twice_daily" Twice daily (morning + evening), "weekly_friday" Weekly on
  // Friday, "weekly_saturday" Weekly on Saturday, "weekly_sunday" Weekly on Sunday
  "digest_frequency": "daily_morning"  // enum
}
```

### currencies

#### `GET /api/v1/currencies/`

**List supported currencies.**

Return all ISO 4217 currency codes supported by the system, sorted by code. Each entry includes the code, English name, and numeric ISO 4217 code. Requires authentication.

**200**

Returns an array of:

```jsonc
{
  "code": "string",                 // string
  "name": "string",                 // string
  // ISO 4217 numeric code; null for historic currencies.
  "numeric": "string"               // string | null
}
```

Common responses: `401` · `429`

### funding-occurrences

#### `GET /api/v1/funding-occurrences/`

**List funding event occurrences.**

Return funding event occurrences for budgets on accounts owned by the authenticated user.  Filterable by bank_account, budget, kind, status (multi-value), and scheduled_date range.  Orderable by scheduled_date or created_at.

| Parameter | In | Type | | Description |
|---|---|---|---|---|
| `bank_account` | query | uuid |  |  |
| `budget` | query | uuid |  |  |
| `date_from` | query | date |  |  |
| `date_to` | query | date |  |  |
| `kind` | query | enum |  | `fund` fund, `recur` recur |
| `ordering` | query | string |  | Which field to use when ordering the results. |
| `status` | query | array of enum |  | `PENDING` Pending, `PARTIAL` Partial, `COMPLETE` Complete, `SKIPPED` Skipped |

**200**

Returns a page of [FundingEventOccurrence](#fundingeventoccurrence-object) (see Pagination).

Common responses: `400` · `401` · `404` · `429`

#### `GET /api/v1/funding-occurrences/{id}/`

**Get a funding event occurrence.**

Return a single funding event occurrence by UUID.

**200**

Returns [FundingEventOccurrence](#fundingeventoccurrence-object).

Common responses: `401` · `404` · `429`

#### FundingEventOccurrence object

```jsonc
{
  "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",  // uuid
  "budget": "3fa85f64-5717-4562-b3fc-2c963f66afa6",  // uuid
  // Funding event discriminator: "fund" or "recur". Stored as the EventKind string
  // value; not exposed in user-facing forms so no choices= is set.
  "kind": "string",                 // string
  // Calendar date the event was scheduled to fire.
  "scheduled_date": "2026-09-29",   // date
  // "PENDING" Pending, "PARTIAL" Partial, "COMPLETE" Complete, "SKIPPED" Skipped
  "status": "PENDING",              // enum
  // Wall-clock time the occurrence reached COMPLETE. Null while
  // PENDING/PARTIAL/SKIPPED.
  "completed_at": "2026-09-29T14:00:00Z",  // date-time | null
  "created_at": "2026-09-29T14:00:00Z",  // date-time
  "modified_at": "2026-09-29T14:00:00Z"  // date-time
}
```

### internal-transactions

#### `GET /api/v1/internal-transactions/`

**List internal transactions.**

Return budget-to-budget transfers belonging to the authenticated user's accounts. Filterable by bank_account, src_budget, dst_budget, and date range (date_from/date_to). Orderable by created_at.

| Parameter | In | Type | | Description |
|---|---|---|---|---|
| `bank_account` | query | uuid |  |  |
| `budget` | query | uuid |  |  |
| `date_from` | query | date-time |  |  |
| `date_to` | query | date-time |  |  |
| `dst_budget` | query | uuid |  |  |
| `ordering` | query | string |  | Which field to use when ordering the results. |
| `src_budget` | query | uuid |  |  |

**200**

Returns a page of [InternalTransaction](#internaltransaction-object) (see Pagination).

Common responses: `400` · `401` · `404` · `429`

#### `POST /api/v1/internal-transactions/`

**Create an internal transaction.**

Transfer money between two budgets in the same bank account. Required: bank_account (UUID), amount, src_budget (UUID), and dst_budget (UUID). The authenticated user is recorded as the actor. Internal transactions are write-once -- to reverse a transfer, create a new one with src and dst swapped.

Example: Move $50.00 from Unallocated to Groceries.

Send [InternalTransaction](#internaltransaction-object) -- its writable fields.

*Example request:*

```json
{
  "bank_account": "6f1c2a3e-8b4d-4e5f-9a1b-2c3d4e5f6a7b",
  "amount": "50.00",
  "src_budget": "e7f8a9b0-c1d2-4e3f-8a4b-5c6d7e8f9a01",
  "dst_budget": "c1d2e3f4-a5b6-4c7d-8e9f-0a1b2c3d4e5f"
}
```

**201**

Returns [InternalTransaction](#internaltransaction-object).

*Example response -- The transfer, with both budgets' balances after it:*

```json
{
  "id": "77777777-8888-4999-8aaa-bbbbbbbbbbbb",
  "bank_account": "6f1c2a3e-8b4d-4e5f-9a1b-2c3d4e5f6a7b",
  "amount": "50.00",
  "amount_currency": "USD",
  "src_budget": "e7f8a9b0-c1d2-4e3f-8a4b-5c6d7e8f9a01",
  "dst_budget": "c1d2e3f4-a5b6-4c7d-8e9f-0a1b2c3d4e5f",
  "actor": 1,
  "effective_date": "2026-09-29T14:10:00Z",
  "src_budget_balance": "1160.53",
  "src_budget_balance_currency": "USD",
  "dst_budget_balance": "390.00",
  "dst_budget_balance_currency": "USD",
  "created_at": "2026-09-29T14:10:00Z",
  "modified_at": "2026-09-29T14:10:00Z"
}
```

Common responses: `400` · `401` · `429`

#### `GET /api/v1/internal-transactions/{id}/`

**Get internal transaction details.**

Return a single internal transaction by UUID.

**200**

Returns [InternalTransaction](#internaltransaction-object).

Common responses: `401` · `404` · `429`

#### InternalTransaction object

```jsonc
{
  "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",  // uuid · read-only
  "bank_account": "3fa85f64-5717-4562-b3fc-2c963f66afa6",  // uuid · required
  "amount": "125.00",               // decimal · required
  // ISO 4217 currency of `amount`. Optional: defaults to the bank account's currency,
  // and any other currency is refused.
  "amount_currency": "USD",         // string · optional
  "src_budget": "3fa85f64-5717-4562-b3fc-2c963f66afa6",  // uuid · required
  "dst_budget": "3fa85f64-5717-4562-b3fc-2c963f66afa6",  // uuid · required
  "actor": 0,                       // integer · read-only
  "effective_date": "2026-09-29T14:00:00Z",  // date-time · optional
  "src_budget_balance": "125.00",   // decimal · read-only
  "src_budget_balance_currency": "USD",  // string · read-only
  "dst_budget_balance": "125.00",   // decimal · read-only
  "dst_budget_balance_currency": "USD",  // string · read-only
  "created_at": "2026-09-29T14:00:00Z",  // date-time · read-only
  "modified_at": "2026-09-29T14:00:00Z"  // date-time · read-only
}
```

### invitations

#### `GET /api/v1/invitations/{token}/`

**Get invitation details (public).**

Return bank account name, current owners, and invitee status for the invitation identified by *token*. No authentication required -- the token is the credential. Used by native apps to render the acceptance UI; the Django template view renders this server-side.

**200**

Returns:

```jsonc
{
  "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",  // uuid
  // "pending" Pending, "accepted" Accepted, "declined" Declined, "cancelled" Cancelled,
  // "expired" Expired
  "status": "pending",              // enum
  // Email address the invitation was sent to. Immutable after creation.
  "invitee_email": "user@example.com",  // email
  "bank_account_name": "string",    // string
  "bank_name": "string",            // string
  "current_owners": ["string"],     // array of string
  "is_new_user": false,             // boolean
  "expires_at": "2026-09-29T14:00:00Z"  // date-time
}
```

Errors:

- **404** (Error) -- Invitation not found.

Common responses: `401` · `429`

#### `POST /api/v1/invitations/{token}/accept/`

**Accept an invitation (public).**

Accept the co-ownership invitation identified by *token*. Adds the invitee to the account's owners. For brand-new users (no password set), a password-reset email is also dispatched. No authentication required.

**200** -- no body.

Errors:

- **400** (Error) -- Invitation expired, cancelled, or already resolved.
- **404** (Error) -- Invitation not found.

Common responses: `401` · `429`

#### `POST /api/v1/invitations/{token}/decline/`

**Decline an invitation (public).**

Decline the co-ownership invitation identified by *token*. No authentication required.

**200** -- no body.

Errors:

- **400** (Error) -- Invitation expired, cancelled, or already resolved.
- **404** (Error) -- Invitation not found.

Common responses: `401` · `429`

### notification-preferences

#### `GET /api/v1/notification-preferences/`

**List notification preferences.**

Return all registered notification kinds merged with the authenticated user's preferences. Kinds without a stored preference fall back to the registry default_delivery_mode.

**200**

Returns an array of [NotificationPreference](#notificationpreference-object).

Common responses: `401` · `429`

#### `PATCH /api/v1/notification-preferences/{kind}/`

**Update a notification preference.**

Set delivery_mode ('digest', 'immediate', or 'off') for a single notification kind. Returns 400 if the kind has can_suppress=False. Returns 404 if the kind is not registered.

Send [NotificationPreference](#notificationpreference-object) -- any subset of its writable fields.

**200**

Returns [NotificationPreference](#notificationpreference-object).

Common responses: `400` · `401` · `404` · `429`

#### NotificationPreference object

```jsonc
{
  "kind": "string",                 // string
  "display_name": "string",         // string
  "can_suppress": false,            // boolean
  // "digest" Digest, "immediate" Immediate, "off" Off
  "delivery_mode": "digest"         // enum
}
```

### transaction-categories

#### `GET /api/v1/transaction-categories/`

**List transaction categories.**

Return the transaction categories visible to the authenticated user: the global base set, the user's own custom categories, categories owned by users they co-own a bank account with, and categories still referenced by the user's transactions after sharing ended.  Filterable by group, archived, and scope (global|mine|shared).  Searchable by group and name.

| Parameter | In | Type | | Description |
|---|---|---|---|---|
| `archived` | query | boolean |  |  |
| `group` | query | string |  |  |
| `ordering` | query | string |  | Which field to use when ordering the results. |
| `scope` | query | enum |  | `global` Global, `mine` Mine, `shared` Shared |
| `search` | query | string |  | A search term. |

**200**

Returns a page of [TransactionCategory](#transactioncategory-object) (see Pagination).

Common responses: `400` · `401` · `404` · `429`

#### `POST /api/v1/transaction-categories/`

**Create a transaction category.**

Create a custom category owned by the authenticated user (global categories are managed via the admin).  Group and name are whitespace-normalized; case-insensitive duplicates of global rows or the user's own rows are rejected.

Send [TransactionCategory](#transactioncategory-object) -- its writable fields.

**201**

Returns [TransactionCategory](#transactioncategory-object).

Common responses: `400` · `401` · `429`

#### `GET /api/v1/transaction-categories/{id}/`

**Get transaction category details.**

Return a single visible category by UUID.

**200**

Returns [TransactionCategory](#transactioncategory-object).

Common responses: `401` · `404` · `429`

#### `PUT /api/v1/transaction-categories/{id}/`

**Update a transaction category.**

Full update of a category.  Only the owner may update; global categories are managed via the admin.

Send [TransactionCategory](#transactioncategory-object) -- its writable fields.

**200**

Returns [TransactionCategory](#transactioncategory-object).

Errors:

- **403** (Error) -- The category is global or owned by someone else; only its owner may change it.

Common responses: `400` · `401` · `404` · `429`

#### `PATCH /api/v1/transaction-categories/{id}/`

**Partially update a transaction category.**

Partial update of a category.  Only the owner may update; global categories are managed via the admin.

Send [TransactionCategory](#transactioncategory-object) -- any subset of its writable fields.

**200**

Returns [TransactionCategory](#transactioncategory-object).

Errors:

- **403** (Error) -- The category is global or owned by someone else; only its owner may change it.

Common responses: `400` · `401` · `404` · `429`

#### `DELETE /api/v1/transaction-categories/{id}/`

**Delete a transaction category.**

Delete a category.  Only the owner may delete; global categories are managed via the admin.  A category still referenced by transactions or allocations cannot be deleted (409) -- archive it instead.

**204** -- no body.

Errors:

- **403** (Error) -- The category is global or owned by someone else; only its owner may change it.
- **409** (Error) -- The category is referenced by transactions or allocations; archive it instead.

Common responses: `401` · `404` · `429`

#### `POST /api/v1/transaction-categories/{id}/archive/`

**Archive a transaction category.**

Archive a category so pickers hide it while existing references stay valid.  Only the owner may archive; global categories are managed via the admin.

**200**

Returns [TransactionCategory](#transactioncategory-object).

Errors:

- **403** (Error) -- The category is global or owned by someone else; only its owner may change it.

Common responses: `401` · `404` · `429`

#### TransactionCategory object

```jsonc
{
  "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",  // uuid · read-only
  "group": "string",                // string · required
  "name": "string",                 // string · required
  // Canonical display form: '{group} : {name}'.
  "full_name": "string",            // string · read-only
  // Owner username; null for a global category.
  "owner": "string",                // string | null · read-only
  // Archived categories are hidden from pickers but remain valid on existing
  // transactions and allocations.
  "archived": false,                // boolean · read-only
  "created_at": "2026-09-29T14:00:00Z",  // date-time · read-only
  "modified_at": "2026-09-29T14:00:00Z"  // date-time · read-only
}
```

### transactions

#### `GET /api/v1/transactions/`

**List transactions.**

Return transactions belonging to the authenticated user's accounts, each with all of its allocations embedded. Filterable by bank_account, budget (transactions with an allocation to that budget), unallocated (true: no allocation to a budget other than the account's Unallocated budget), pending status, transaction_type, date range (date_from/date_to), category, and merchant fields. Searchable by description, raw_description, and party. Orderable by transaction_date, amount, or created_at.

| Parameter | In | Type | | Description |
|---|---|---|---|---|
| `bank_account` | query | uuid |  |  |
| `budget` | query | uuid |  |  |
| `category` | query | uuid |  |  |
| `category_group` | query | string |  |  |
| `date_from` | query | date-time |  |  |
| `date_to` | query | date-time |  |  |
| `has_details` | query | boolean |  |  |
| `merchant_category_code` | query | string |  |  |
| `merchant_city` | query | string |  |  |
| `merchant_intermediary` | query | string |  |  |
| `merchant_name` | query | string |  |  |
| `merchant_region` | query | string |  |  |
| `ordering` | query | string |  | Which field to use when ordering the results. |
| `pending` | query | boolean |  |  |
| `posted_date_from` | query | date-time |  |  |
| `posted_date_to` | query | date-time |  |  |
| `search` | query | string |  | A search term. |
| `transaction_type` | query | enum |  | `signature_purchase` Signature Purchase, `ach` ACH, `round-up_transfer` Round-up Transfer, `protected_goal_account_transfer` Protected Goal Account Transfer, `fee` Fee, `pin_purchase` Pin Purchase, `signature_credit` Signature Credit, `interest_credit` Interest Credit, `shared_transfer` Shared Transfer, `courtesy_credit` Courtesy Credit, `atm_withdrawal` ATM Withdrawal, `bill_payment` Bill Payment, `bank_generated_credit` Bank Generated Credit, `wire_transfer` Wire Transfer, `check_deposit` Check Deposit, `check` Check, `c2c` c2c, `migration_interbank_transfer` Migration Interbank Transfer, `balance_sweep` Balance Sweep, `ach_reversal` ACH Reversal, `adjustment` Adjustment, `signature_return` Signature return, `fx_order` FX Order |
| `unallocated` | query | boolean |  |  |
| `uncategorized` | query | boolean |  |  |
| `virtual_card_last4` | query | string |  |  |

**200**

Returns a page of [Transaction](#transaction-object) (see Pagination).

Common responses: `400` · `401` · `404` · `429`

#### `POST /api/v1/transactions/`

**Create a transaction.**

Create a new bank transaction. Required: bank_account (UUID), amount, transaction_date, transaction_type, and raw_description. A default TransactionAllocation to the bank account's unallocated budget is auto-created. After creation, only transaction_type, memo, and description are updatable.

Send [Transaction](#transaction-object) -- its writable fields.

**201**

Returns [Transaction](#transaction-object).

Common responses: `400` · `401` · `429`

#### `GET /api/v1/transactions/{id}/`

**Get transaction details.**

Return a single transaction by UUID, with all of its allocations embedded.

**200**

Returns [Transaction](#transaction-object).

Common responses: `401` · `404` · `429`

#### `PUT /api/v1/transactions/{id}/`

**Update a transaction.**

Full update of a transaction. Only transaction_type, memo, and description are mutable after creation.

Send [Transaction](#transaction-object) -- its writable fields.

**200**

Returns [Transaction](#transaction-object).

Common responses: `400` · `401` · `404` · `429`

#### `PATCH /api/v1/transactions/{id}/`

**Partially update a transaction.**

Partial update of a transaction. Only transaction_type, memo, and description are mutable after creation.

Send [Transaction](#transaction-object) -- any subset of its writable fields.

**200**

Returns [Transaction](#transaction-object).

Common responses: `400` · `401` · `404` · `429`

#### `DELETE /api/v1/transactions/{id}/`

**Delete a transaction.**

Delete a transaction. Balance changes are reversed by the pre_delete signal. Associated allocations are cascade-deleted.

**204** -- no body.

Common responses: `401` · `404` · `429`

#### `POST /api/v1/transactions/{id}/resolve-pending/`

**Resolve a pending transaction to posted.**

Transition a pending transaction to posted status. Supplies the bank-confirmed posted date and optionally a final settled amount (which may differ from the pending estimate). The bank account's posted_balance is credited; if the amount changed, available_balance and the Unallocated allocation are adjusted atomically.

Send:

```jsonc
{
  "posted_date": "2026-09-29T14:00:00Z",  // date-time · required
  "amount": "125.00",               // decimal | null · optional
  // ISO 4217 currency of `amount`. Optional: defaults to the bank account's currency,
  // and any other currency is refused.
  "amount_currency": "USD"          // string · optional
}
```

**200**

Returns [Transaction](#transaction-object).

Common responses: `400` · `401` · `404` · `429`

#### `POST /api/v1/transactions/{id}/splits/`

**Declare transaction splits.**

Declaratively set how a transaction's amount is split across budgets. All referenced budgets must belong to the same bank account as the transaction. The backend reconciles existing allocations to match: creating, updating, or deleting as needed. Any unallocated remainder gets an allocation to the account's unallocated budget. Returns all allocations for this transaction after reconciliation.

Example: Put $60.00 of an $82.47 purchase in Groceries.

The $22.47 not declared goes to the account's unallocated budget.  Amounts are positive; the sign follows the transaction.

Send:

```jsonc
{
  // Map of budget UUID → amount. Amounts must not exceed the transaction total. Omitted
  // remainder is assigned to the unallocated budget.
  "splits": {"<key>": "125.00"}     // map of decimal · required
}
```

*Example request:*

```json
{
  "splits": {
    "c1d2e3f4-a5b6-4c7d-8e9f-0a1b2c3d4e5f": "60.00"
  }
}
```

**200**

Returns an array of [TransactionAllocation](#transactionallocation-object).

*Example response -- The purchase's allocations after the split:*

```json
[
  {
    "id": "66666666-7777-4888-8999-aaaaaaaaaaaa",
    "transaction": "b2e4c6d8-1a3f-4b5c-8d7e-9f0a1b2c3d4e",
    "budget": "e7f8a9b0-c1d2-4e3f-8a4b-5c6d7e8f9a01",
    "amount": "-22.47",
    "amount_currency": "USD",
    "budget_balance": "1210.53",
    "budget_balance_currency": "USD",
    "category": "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d",
    "category_full_name": "Food & Drink : Groceries",
    "memo": null,
    "created_at": "2026-09-28T18:40:05Z",
    "modified_at": "2026-09-29T14:02:11Z"
  },
  {
    "id": "11111111-2222-4333-8444-555555555555",
    "transaction": "b2e4c6d8-1a3f-4b5c-8d7e-9f0a1b2c3d4e",
    "budget": "c1d2e3f4-a5b6-4c7d-8e9f-0a1b2c3d4e5f",
    "amount": "-60.00",
    "amount_currency": "USD",
    "budget_balance": "340.00",
    "budget_balance_currency": "USD",
    "category": "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d",
    "category_full_name": "Food & Drink : Groceries",
    "memo": null,
    "created_at": "2026-09-29T14:02:11Z",
    "modified_at": "2026-09-29T14:02:11Z"
  }
]
```

Common responses: `400` · `401` · `404` · `429`

#### Transaction object

```jsonc
{
  "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",  // uuid · read-only
  "bank_account": "3fa85f64-5717-4562-b3fc-2c963f66afa6",  // uuid · required
  "amount": "125.00",               // decimal · required
  // ISO 4217 currency of `amount`. Optional: defaults to the bank account's currency,
  // and any other currency is refused.
  "amount_currency": "USD",         // string · optional
  "party": "string",                // string | null · read-only
  "posted_date": "2026-09-29T14:00:00Z",  // date-time · required
  "transaction_date": "2026-09-29T14:00:00Z",  // date-time | null · optional
  // "signature_purchase" Signature Purchase, "ach" ACH, "round-up_transfer" Round-up
  // Transfer, "protected_goal_account_transfer" Protected Goal Account Transfer, "fee"
  // Fee, "pin_purchase" Pin Purchase, "signature_credit" Signature Credit,
  // "interest_credit" Interest Credit, "shared_transfer" Shared Transfer,
  // "courtesy_credit" Courtesy Credit, "atm_withdrawal" ATM Withdrawal, "bill_payment"
  // Bill Payment, "bank_generated_credit" Bank Generated Credit, "wire_transfer" Wire
  // Transfer, "check_deposit" Check Deposit, "check" Check, "c2c",
  // "migration_interbank_transfer" Migration Interbank Transfer, "balance_sweep"
  // Balance Sweep, "ach_reversal" ACH Reversal, "adjustment" Adjustment,
  // "signature_return" Signature return, "fx_order" FX Order
  "transaction_type": "signature_purchase",  // enum · required
  "pending": false,                 // boolean · optional
  "memo": "string",                 // string | null · optional
  "raw_description": "string",      // string · required
  "description": "string",          // string · optional
  "description_user_edited": false,  // boolean · read-only
  "category": "3fa85f64-5717-4562-b3fc-2c963f66afa6",  // uuid | null · optional
  "category_full_name": "string",   // string | null · read-only
  "merchant_name": "string",        // string | null · read-only
  "merchant_intermediary": "string",  // string | null · read-only
  "merchant_address": "string",     // string | null · optional
  "merchant_city": "string",        // string | null · optional
  "merchant_region": "string",      // string | null · optional
  "merchant_country": "string",     // string | null · optional
  "merchant_latitude": "125.00",    // decimal | null · optional
  "merchant_longitude": "125.00",   // decimal | null · optional
  "merchant_category": "string",    // string | null · read-only
  "merchant_category_code": "string",  // string | null · read-only
  "virtual_card_number": "string",  // string | null · read-only
  "has_details": false,             // boolean · read-only
  "allocations": [{...}],           // array of TransactionAllocation · read-only
  "bank_transaction_id": "string",  // string | null · optional
  "linked_transaction": "3fa85f64-5717-4562-b3fc-2c963f66afa6",  // uuid | null · read-only
  // Posted Balance does not include pending debits.
  "bank_account_posted_balance": "125.00",  // decimal · read-only
  "bank_account_posted_balance_currency": "USD",  // string · read-only
  // Available Balance has pending debits deducted.
  "bank_account_available_balance": "125.00",  // decimal · read-only
  "bank_account_available_balance_currency": "USD",  // string · read-only
  "image": "https://mibudge.example.com/...",  // uri | null · optional
  "document": "https://mibudge.example.com/...",  // uri | null · optional
  "created_at": "2026-09-29T14:00:00Z",  // date-time · read-only
  "modified_at": "2026-09-29T14:00:00Z"  // date-time · read-only
}
```

Nested objects: [TransactionAllocation](#transactionallocation-object).

### users

#### `GET /api/v1/users/`

**List users (staff only).**

Return all users. Restricted to staff/admin users.

| Parameter | In | Type | | Description |
|---|---|---|---|---|
| `ordering` | query | string |  | Which field to use when ordering the results. |

**200**

Returns a page of [User](#user-object) (see Pagination).

Common responses: `401` · `403` · `404` · `429`

#### `GET /api/v1/users/{username}/`

**Get user details (staff only).**

Return a single user by username. Restricted to staff/admin users.

**200**

Returns [User](#user-object).

Common responses: `401` · `403` · `404` · `429`

#### `PUT /api/v1/users/{username}/`

**Update a user (staff only).**

Full update of a user profile. Restricted to staff/admin users.

Send [User](#user-object) -- its writable fields.

**200**

Returns [User](#user-object).

Common responses: `400` · `401` · `403` · `404` · `429`

#### `PATCH /api/v1/users/{username}/`

**Partially update a user (staff only).**

Partial update of a user profile. Restricted to staff/admin users.

Send [User](#user-object) -- any subset of its writable fields.

**200**

Returns [User](#user-object).

Common responses: `400` · `401` · `403` · `404` · `429`

#### `GET /api/v1/users/me/`

**Get or update current user profile.**

GET returns the authenticated user's own profile. PATCH allows updating the name field. Available to any authenticated user (not restricted to staff). GET is also available to machine credentials (API keys) -- importers read the timezone field; PATCH requires an interactive login session.

**200**

Returns [User](#user-object).

Common responses: `401` · `429`

#### `PATCH /api/v1/users/me/`

**Get or update current user profile.**

GET returns the authenticated user's own profile. PATCH allows updating the name field. Available to any authenticated user (not restricted to staff). GET is also available to machine credentials (API keys) -- importers read the timezone field; PATCH requires an interactive login session.

Send [User](#user-object) -- any subset of its writable fields.

**200**

Returns [User](#user-object).

Common responses: `400` · `401` · `403` · `429`

#### `GET /api/v1/users/me/api-keys/`

**List the current user's API keys.**

Return all API keys (active, expired, and revoked) belonging to the authenticated user.  Key material is never included -- only the displayable prefix.

**200**

Returns a page of [APIKey](#apikey-object) (see Pagination).

Common responses: `401` · `403` · `404` · `429`

#### `POST /api/v1/users/me/api-keys/`

**Create an API key.**

Create a new API key for the authenticated user.  ``expiry_days`` sets the key's lifetime in days (the UI presets are 30 / 60 / 90 / 365); omit it or pass null for a key that never expires.

The response is the **only** time the plaintext ``key`` is returned; it cannot be recovered afterwards.

Send:

```jsonc
{
  "name": "string",                 // string · required
  "expiry_days": 0                  // integer | null · optional
}
```

**201**

Returns:

```jsonc
{
  "uuid": "3fa85f64-5717-4562-b3fc-2c963f66afa6",  // uuid
  // User-supplied label identifying what this key is for.
  "name": "string",                 // string
  "prefix": "string",               // string
  "expires_at": "2026-09-29T14:00:00Z",  // date-time | null
  "last_used_at": "2026-09-29T14:00:00Z",  // date-time | null
  "revoked_at": "2026-09-29T14:00:00Z",  // date-time | null
  "created_at": "2026-09-29T14:00:00Z",  // date-time
  "key": "string"                   // string
}
```

Common responses: `400` · `401` · `403` · `429`

#### `GET /api/v1/users/me/api-keys/{uuid}/`

**Get one of the current user's API keys.**

Return a single API key by its UUID.

**200**

Returns [APIKey](#apikey-object).

Common responses: `401` · `403` · `404` · `429`

#### `POST /api/v1/users/me/api-keys/{uuid}/revoke/`

**Revoke an API key.**

Permanently revoke an API key.  Revoked keys stop authenticating immediately but remain listed for audit purposes.  Revocation cannot be undone.

**200**

Returns [APIKey](#apikey-object).

Errors:

- **400** (Error) -- The key is already revoked.

Common responses: `401` · `403` · `404` · `429`

#### `POST /api/v1/users/me/api-keys/revoke-all/`

**Revoke every API key.**

Revoke all of the current user's active API keys at once, e.g. after a suspected account takeover.  Revoked keys stop authenticating immediately and remain listed for audit purposes.  Revocation cannot be undone.  Returns how many keys were revoked; 0 when none were active.

**200**

Returns:

```jsonc
{
  "revoked": 0                      // integer
}
```

Common responses: `401` · `403` · `429`

#### `POST /api/v1/users/me/change-email/`

**Request an email address change.**

Initiate a self-service email change.  Sends a verification link to the new address and a revocation link to the old address.  Returns 403 if the user has no usable password; 409 if new_email is already taken or a revocation window is currently open for this account.

Send:

```jsonc
{
  "new_email": "user@example.com"   // email · required
}
```

**201** -- no body.

Errors:

- **403** (Error) -- The account has no password yet, or the credentials are not interactive.
- **409** (ValidationError) -- The address is taken ('new_email'), or a revocation window is still open ('detail').

Common responses: `400` · `401` · `429`

#### `POST /api/v1/users/me/change-email/{token}/confirm/`

**Confirm an email address change (new-address token).**

Verify a pending email change using the token from the verification link sent to the new address.  No authentication required -- the token is the credential.

**Dual-path note:** The email link points to a Django GET view at ``/users/email-change/{token}/confirm/`` which processes the action and redirects the browser to the SPA result page.  Native apps that register mibudge.money as a Universal Link (iOS) or App Link (Android) intercept that URL and call this endpoint instead, receiving JSON and controlling their own UI.

| Parameter | In | Type | | Description |
|---|---|---|---|---|
| `token` | path | string | required | The email-change verification token. |

**200** -- no body.

Errors:

- **400** (Error) -- The link is unknown, expired, revoked or already used.
- **409** (Error) -- The address was taken meanwhile.

Common responses: `401` · `429`

#### `POST /api/v1/users/me/change-email/{token}/revoke/`

**Revoke an email address change ('this wasn't me').**

Cancel a pending or recently confirmed email change using the token from the notification sent to the old address.  Valid for up to 7 days after confirmation.  No authentication required -- the token is the credential.

On post-confirmation revocation the email is reverted and all active sessions are invalidated.

**Dual-path note:** See ``change_email_confirm`` -- the same Universal Link / App Link pattern applies here.

| Parameter | In | Type | | Description |
|---|---|---|---|---|
| `token` | path | string | required | The email-change revocation token. |

**200** -- no body.

Errors:

- **400** (Error) -- The link is unknown, or its revocation window has closed.

Common responses: `401` · `429`

#### `POST /api/v1/users/me/change-password/`

**Change current user's password.**

Change the authenticated user's password. Requires the current password for verification. The new password must score at least 2 on the zxcvbn scale.

Every other session ends: its refresh token is revoked, and its access token stops working when it expires (at most 60 minutes).  The caller stays signed in with a new refresh cookie set on this response.  API keys are not affected.

Send:

```jsonc
{
  "current_password": "string",     // string · required
  "new_password": "string",         // string · required
  "confirm_password": "string"      // string · required
}
```

**204** -- no body.

Common responses: `400` · `401` · `403` · `429`

#### `GET /api/v1/users/me/invitations/`

**List current user's outgoing pending invitations.**

Return all pending co-ownership invitations sent by the authenticated user, across all accounts.

**200**

Returns an array of [BankAccountInvitation](#bankaccountinvitation-object).

Common responses: `401` · `403` · `429`

#### APIKey object

```jsonc
{
  "uuid": "3fa85f64-5717-4562-b3fc-2c963f66afa6",  // uuid
  // User-supplied label identifying what this key is for.
  "name": "string",                 // string
  "prefix": "string",               // string
  "expires_at": "2026-09-29T14:00:00Z",  // date-time | null
  "last_used_at": "2026-09-29T14:00:00Z",  // date-time | null
  "revoked_at": "2026-09-29T14:00:00Z",  // date-time | null
  "created_at": "2026-09-29T14:00:00Z"  // date-time
}
```

#### User object

```jsonc
{
  // Required. 150 characters or fewer. Letters, digits and @/./+/-/_ only.
  "username": "string",             // string · read-only
  // Login email address; blank for system accounts.
  "email": "string",                // string · read-only
  "name": "string",                 // string · optional
  "url": "https://mibudge.example.com/...",  // uri · read-only
  "default_bank_account": "3fa85f64-5717-4562-b3fc-2c963f66afa6",  // uuid | null · optional
  "timezone": "string",             // string · optional
  // Return True if the user has a usable (non-unusable) password set.
  "has_usable_password": false      // boolean · read-only
}
```
