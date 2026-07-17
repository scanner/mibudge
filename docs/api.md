# mibudge API

REST API for the mibudge personal budgeting service.

## Authentication

All endpoints require JWT authentication via `Authorization: Bearer <token>` header. Obtain tokens through the login flow; refresh via `POST /api/token/refresh/` (httpOnly cookie).

## Permissions

- **Banks**: read-only, any authenticated user.
- **Users**: list/retrieve/update restricted to staff; `/api/v1/users/me/` available to all authenticated users.
- **All other resources** (bank accounts, budgets, transactions, allocations, internal transactions): scoped to bank account ownership. Only users in an account's `owners` M2M can access that account and its related objects. Staff and superuser status does not bypass ownership checks.

## Money fields

Monetary values are represented as a decimal amount paired with an ISO 4217 currency code (e.g. `amount` + `amount_currency`). Currency defaults to the account's currency if not specified.

**Version:** 1.0.0

## Authentication

- **apiKeyAuth**: `apiKey` (in: `header`, name: `Authorization`)
- **jwtAuth**: `http` (in: ``, name: ``)

## Endpoints

### api

#### `POST /api/token/`

**Operation:** `api_token_create`

JWT obtain endpoint that stores the refresh token in an httpOnly
cookie and returns only the access token in the response body.

This is the browser-SPA login flow: JS receives the short-lived
access token (kept in memory); the refresh token is a
Secure/HttpOnly/SameSite=Strict cookie that JS cannot read,
and that the browser sends automatically to /api/token/refresh/.

**Request Body** (`application/json`):

- **`email`** (`string`) *(required)*
- **`password`** (`string`) *(required)*

**Request Body** (`application/x-www-form-urlencoded`):

- **`email`** (`string`) *(required)*
- **`password`** (`string`) *(required)*

**Request Body** (`multipart/form-data`):

- **`email`** (`string`) *(required)*
- **`password`** (`string`) *(required)*

**Response 200:** No response body

#### `POST /api/token/refresh/`

**Operation:** `api_token_refresh_create`

JWT refresh endpoint that reads the refresh token from the httpOnly
cookie rather than the request body.

On success, returns {"access": "<new_access_token>"} in JSON.
When token rotation is enabled, also rotates the refresh cookie so
the 14-day sliding window resets with each use.

**Request Body** (`application/json`):

- **`refresh`** (`string`) *(required)*

**Request Body** (`application/x-www-form-urlencoded`):

- **`refresh`** (`string`) *(required)*

**Request Body** (`multipart/form-data`):

- **`refresh`** (`string`) *(required)*

**Response 200:** 

- **`access`** (`string`) *(required, read-only)*
- **`refresh`** (`string`) *(required)*

### allocations

#### `GET /api/v1/allocations/`

**Operation:** `allocations_list`

Return allocations belonging to the authenticated user's transactions. Filterable by transaction, budget, and category. Orderable by created_at.

**Parameters:**

- `bank_account` (query, optional)
- `budget` (query, optional)
- `category` (query, optional)
- `category_group` (query, optional)
- `ordering` (query, optional) — Which field to use when ordering the results.
- `page` (query, optional) — A page number within the paginated result set.
- `page_size` (query, optional) — Number of results to return per page.
- `transaction` (query, optional)
- `uncategorized` (query, optional)

**Response 200:** 

- **`count`** (`integer`) *(required)*
- **`next`** (`string`)
- **`previous`** (`string`)
- **`results`** (`array`) *(required)*

#### `GET /api/v1/allocations/{id}/`

**Operation:** `allocations_retrieve`

Return a single transaction allocation by UUID.

**Parameters:**

- `id` (path, required)

**Response 200:** 

- **`id`** (`string`) *(required, read-only)*
- **`transaction`** (`string`) *(required)*
- **`budget`** (`string`)
- **`amount`** (`string`) *(required)*
- **`amount_currency`** (`string`) *(required, read-only)*
- **`budget_balance`** (`string`) *(required, read-only)*
- **`budget_balance_currency`** (`string`) *(required, read-only)*
- **`category`** (`string`)
- **`category_full_name`** (`string`) *(required, read-only)*
- **`memo`** (`string`)
- **`created_at`** (`string`) *(required, read-only)*
- **`modified_at`** (`string`) *(required, read-only)*

### bank-accounts

#### `GET /api/v1/bank-accounts/`

**Operation:** `bank_accounts_list`

Return bank accounts owned by the authenticated user. Filterable by account_type. Orderable by name or created_at.

**Parameters:**

- `account_type` (query, optional) — * `C` - Checking
* `S` - Savings
* `X` - Credit Card
- `ordering` (query, optional) — Which field to use when ordering the results.
- `page` (query, optional) — A page number within the paginated result set.
- `page_size` (query, optional) — Number of results to return per page.

**Response 200:** 

- **`count`** (`integer`) *(required)*
- **`next`** (`string`)
- **`previous`** (`string`)
- **`results`** (`array`) *(required)*

#### `POST /api/v1/bank-accounts/`

**Operation:** `bank_accounts_create`

Create a new bank account. The authenticated user is automatically added as an owner. An 'Unallocated' budget is auto-created by a post_save signal. Optionally set initial posted_balance, available_balance, and currency (all immutable after creation).

**Request Body** (`application/json`):

- **`name`** (`string`) *(required)*
- **`bank`** (`string`) *(required)*
- **`account_type`** (`string`) — * `C` - Checking
* `S` - Savings
* `X` - Credit Card Enum: ['C', 'S', 'X']
- **`account_number`** (`string`)
- **`currency`** (`string`) — ISO 4217 currency code (e.g. USD, EUR, GBP).
- **`posted_balance`** (`string`)
- **`available_balance`** (`string`)
- **`auto_funding_enabled`** (`boolean`) — When enabled (the default), scheduled funding and recurrence events run automatically for this account.  Disable to opt out of automation and drive funding entirely from the 'Run funding now' button.

**Request Body** (`application/x-www-form-urlencoded`):

- **`name`** (`string`) *(required)*
- **`bank`** (`string`) *(required)*
- **`account_type`** (`string`) — * `C` - Checking
* `S` - Savings
* `X` - Credit Card Enum: ['C', 'S', 'X']
- **`account_number`** (`string`)
- **`currency`** (`string`) — ISO 4217 currency code (e.g. USD, EUR, GBP).
- **`posted_balance`** (`string`)
- **`available_balance`** (`string`)
- **`auto_funding_enabled`** (`boolean`) — When enabled (the default), scheduled funding and recurrence events run automatically for this account.  Disable to opt out of automation and drive funding entirely from the 'Run funding now' button.

**Request Body** (`multipart/form-data`):

- **`name`** (`string`) *(required)*
- **`bank`** (`string`) *(required)*
- **`account_type`** (`string`) — * `C` - Checking
* `S` - Savings
* `X` - Credit Card Enum: ['C', 'S', 'X']
- **`account_number`** (`string`)
- **`currency`** (`string`) — ISO 4217 currency code (e.g. USD, EUR, GBP).
- **`posted_balance`** (`string`)
- **`available_balance`** (`string`)
- **`auto_funding_enabled`** (`boolean`) — When enabled (the default), scheduled funding and recurrence events run automatically for this account.  Disable to opt out of automation and drive funding entirely from the 'Run funding now' button.

**Response 201:** 

- **`id`** (`string`) *(required, read-only)*
- **`name`** (`string`) *(required)*
- **`bank`** (`string`) *(required)*
- **`owners`** (`array`) *(required, read-only)*
- **`account_type`** (`string`) — * `C` - Checking
* `S` - Savings
* `X` - Credit Card Enum: ['C', 'S', 'X']
- **`account_number`** (`string`)
- **`currency`** (`string`) — ISO 4217 currency code (e.g. USD, EUR, GBP).
- **`posted_balance`** (`string`)
- **`posted_balance_currency`** (`string`) *(required, read-only)*
- **`available_balance`** (`string`)
- **`available_balance_currency`** (`string`) *(required, read-only)*
- **`unallocated_budget`** (`string`) *(required, read-only)*
- **`auto_funding_enabled`** (`boolean`) — When enabled (the default), scheduled funding and recurrence events run automatically for this account.  Disable to opt out of automation and drive funding entirely from the 'Run funding now' button.
- **`last_imported_at`** (`string`) *(required, read-only)* — Wall-clock time of the most recent completed import for this account.
- **`last_posted_through`** (`string`) *(required, read-only)* — Latest posted_date seen in the most recent import batch. The funding engine will not process events dated after this value.
- **`created_at`** (`string`) *(required, read-only)*
- **`modified_at`** (`string`) *(required, read-only)*

#### `GET /api/v1/bank-accounts/{id}/`

**Operation:** `bank_accounts_retrieve`

Return a single bank account by UUID.

**Parameters:**

- `id` (path, required)

**Response 200:** 

- **`id`** (`string`) *(required, read-only)*
- **`name`** (`string`) *(required)*
- **`bank`** (`string`) *(required)*
- **`owners`** (`array`) *(required, read-only)*
- **`account_type`** (`string`) — * `C` - Checking
* `S` - Savings
* `X` - Credit Card Enum: ['C', 'S', 'X']
- **`account_number`** (`string`)
- **`currency`** (`string`) — ISO 4217 currency code (e.g. USD, EUR, GBP).
- **`posted_balance`** (`string`)
- **`posted_balance_currency`** (`string`) *(required, read-only)*
- **`available_balance`** (`string`)
- **`available_balance_currency`** (`string`) *(required, read-only)*
- **`unallocated_budget`** (`string`) *(required, read-only)*
- **`auto_funding_enabled`** (`boolean`) — When enabled (the default), scheduled funding and recurrence events run automatically for this account.  Disable to opt out of automation and drive funding entirely from the 'Run funding now' button.
- **`last_imported_at`** (`string`) *(required, read-only)* — Wall-clock time of the most recent completed import for this account.
- **`last_posted_through`** (`string`) *(required, read-only)* — Latest posted_date seen in the most recent import batch. The funding engine will not process events dated after this value.
- **`created_at`** (`string`) *(required, read-only)*
- **`modified_at`** (`string`) *(required, read-only)*

#### `PUT /api/v1/bank-accounts/{id}/`

**Operation:** `bank_accounts_update`

Full update of a bank account. Only 'name' is mutable after creation -- bank, account_type, currency, and balances are rejected if changed.

**Parameters:**

- `id` (path, required)

**Request Body** (`application/json`):

- **`name`** (`string`) *(required)*
- **`bank`** (`string`) *(required)*
- **`account_type`** (`string`) — * `C` - Checking
* `S` - Savings
* `X` - Credit Card Enum: ['C', 'S', 'X']
- **`account_number`** (`string`)
- **`currency`** (`string`) — ISO 4217 currency code (e.g. USD, EUR, GBP).
- **`posted_balance`** (`string`)
- **`available_balance`** (`string`)
- **`auto_funding_enabled`** (`boolean`) — When enabled (the default), scheduled funding and recurrence events run automatically for this account.  Disable to opt out of automation and drive funding entirely from the 'Run funding now' button.

**Request Body** (`application/x-www-form-urlencoded`):

- **`name`** (`string`) *(required)*
- **`bank`** (`string`) *(required)*
- **`account_type`** (`string`) — * `C` - Checking
* `S` - Savings
* `X` - Credit Card Enum: ['C', 'S', 'X']
- **`account_number`** (`string`)
- **`currency`** (`string`) — ISO 4217 currency code (e.g. USD, EUR, GBP).
- **`posted_balance`** (`string`)
- **`available_balance`** (`string`)
- **`auto_funding_enabled`** (`boolean`) — When enabled (the default), scheduled funding and recurrence events run automatically for this account.  Disable to opt out of automation and drive funding entirely from the 'Run funding now' button.

**Request Body** (`multipart/form-data`):

- **`name`** (`string`) *(required)*
- **`bank`** (`string`) *(required)*
- **`account_type`** (`string`) — * `C` - Checking
* `S` - Savings
* `X` - Credit Card Enum: ['C', 'S', 'X']
- **`account_number`** (`string`)
- **`currency`** (`string`) — ISO 4217 currency code (e.g. USD, EUR, GBP).
- **`posted_balance`** (`string`)
- **`available_balance`** (`string`)
- **`auto_funding_enabled`** (`boolean`) — When enabled (the default), scheduled funding and recurrence events run automatically for this account.  Disable to opt out of automation and drive funding entirely from the 'Run funding now' button.

**Response 200:** 

- **`id`** (`string`) *(required, read-only)*
- **`name`** (`string`) *(required)*
- **`bank`** (`string`) *(required)*
- **`owners`** (`array`) *(required, read-only)*
- **`account_type`** (`string`) — * `C` - Checking
* `S` - Savings
* `X` - Credit Card Enum: ['C', 'S', 'X']
- **`account_number`** (`string`)
- **`currency`** (`string`) — ISO 4217 currency code (e.g. USD, EUR, GBP).
- **`posted_balance`** (`string`)
- **`posted_balance_currency`** (`string`) *(required, read-only)*
- **`available_balance`** (`string`)
- **`available_balance_currency`** (`string`) *(required, read-only)*
- **`unallocated_budget`** (`string`) *(required, read-only)*
- **`auto_funding_enabled`** (`boolean`) — When enabled (the default), scheduled funding and recurrence events run automatically for this account.  Disable to opt out of automation and drive funding entirely from the 'Run funding now' button.
- **`last_imported_at`** (`string`) *(required, read-only)* — Wall-clock time of the most recent completed import for this account.
- **`last_posted_through`** (`string`) *(required, read-only)* — Latest posted_date seen in the most recent import batch. The funding engine will not process events dated after this value.
- **`created_at`** (`string`) *(required, read-only)*
- **`modified_at`** (`string`) *(required, read-only)*

#### `PATCH /api/v1/bank-accounts/{id}/`

**Operation:** `bank_accounts_partial_update`

Partial update of a bank account. Only 'name' is mutable after creation.

**Parameters:**

- `id` (path, required)

**Request Body** (`application/json`):

- **`name`** (`string`)
- **`bank`** (`string`)
- **`account_type`** (`string`) — * `C` - Checking
* `S` - Savings
* `X` - Credit Card Enum: ['C', 'S', 'X']
- **`account_number`** (`string`)
- **`currency`** (`string`) — ISO 4217 currency code (e.g. USD, EUR, GBP).
- **`posted_balance`** (`string`)
- **`available_balance`** (`string`)
- **`auto_funding_enabled`** (`boolean`) — When enabled (the default), scheduled funding and recurrence events run automatically for this account.  Disable to opt out of automation and drive funding entirely from the 'Run funding now' button.

**Request Body** (`application/x-www-form-urlencoded`):

- **`name`** (`string`)
- **`bank`** (`string`)
- **`account_type`** (`string`) — * `C` - Checking
* `S` - Savings
* `X` - Credit Card Enum: ['C', 'S', 'X']
- **`account_number`** (`string`)
- **`currency`** (`string`) — ISO 4217 currency code (e.g. USD, EUR, GBP).
- **`posted_balance`** (`string`)
- **`available_balance`** (`string`)
- **`auto_funding_enabled`** (`boolean`) — When enabled (the default), scheduled funding and recurrence events run automatically for this account.  Disable to opt out of automation and drive funding entirely from the 'Run funding now' button.

**Request Body** (`multipart/form-data`):

- **`name`** (`string`)
- **`bank`** (`string`)
- **`account_type`** (`string`) — * `C` - Checking
* `S` - Savings
* `X` - Credit Card Enum: ['C', 'S', 'X']
- **`account_number`** (`string`)
- **`currency`** (`string`) — ISO 4217 currency code (e.g. USD, EUR, GBP).
- **`posted_balance`** (`string`)
- **`available_balance`** (`string`)
- **`auto_funding_enabled`** (`boolean`) — When enabled (the default), scheduled funding and recurrence events run automatically for this account.  Disable to opt out of automation and drive funding entirely from the 'Run funding now' button.

**Response 200:** 

- **`id`** (`string`) *(required, read-only)*
- **`name`** (`string`) *(required)*
- **`bank`** (`string`) *(required)*
- **`owners`** (`array`) *(required, read-only)*
- **`account_type`** (`string`) — * `C` - Checking
* `S` - Savings
* `X` - Credit Card Enum: ['C', 'S', 'X']
- **`account_number`** (`string`)
- **`currency`** (`string`) — ISO 4217 currency code (e.g. USD, EUR, GBP).
- **`posted_balance`** (`string`)
- **`posted_balance_currency`** (`string`) *(required, read-only)*
- **`available_balance`** (`string`)
- **`available_balance_currency`** (`string`) *(required, read-only)*
- **`unallocated_budget`** (`string`) *(required, read-only)*
- **`auto_funding_enabled`** (`boolean`) — When enabled (the default), scheduled funding and recurrence events run automatically for this account.  Disable to opt out of automation and drive funding entirely from the 'Run funding now' button.
- **`last_imported_at`** (`string`) *(required, read-only)* — Wall-clock time of the most recent completed import for this account.
- **`last_posted_through`** (`string`) *(required, read-only)* — Latest posted_date seen in the most recent import batch. The funding engine will not process events dated after this value.
- **`created_at`** (`string`) *(required, read-only)*
- **`modified_at`** (`string`) *(required, read-only)*

#### `DELETE /api/v1/bank-accounts/{id}/`

**Operation:** `bank_accounts_destroy`

Delete a bank account and all associated budgets, transactions, and allocations.

**Parameters:**

- `id` (path, required)

**Response 204:** No response body

#### `GET /api/v1/bank-accounts/{id}/funding-event-dates/`

**Operation:** `bank_accounts_funding_event_dates_retrieve`

Return all dates in (after, before] on which at least one funding or recurrence event is due for this account.  The importer uses this to find batch-split boundaries.

**Parameters:**

- `id` (path, required)

**Response 200:** Sorted list of event dates.

- **`dates`** (`array`)

#### `GET /api/v1/bank-accounts/{id}/funding-summary/`

**Operation:** `bank_accounts_funding_summary_retrieve`

Return the total amounts that will be automatically funded at the next event for each distinct funding schedule on this account.  Only active, schedulable budgets are included -- paused, archived, completed goals, and RECURRING budgets that delegate to a fill-up goal are excluded.  Results are grouped by funding schedule (RRULE string) and sorted by next event date.

**Parameters:**

- `id` (path, required)

**Response 200:** Per-schedule funding totals.

- **`schedules`** (`array`)
- **`total_amount`** (`string`)
- **`currency`** (`string`)

#### `GET /api/v1/bank-accounts/{id}/invitations/`

**Operation:** `bank_accounts_invitations_list`

Returns all pending invitations for this bank account.

**Parameters:**

- `account_type` (query, optional) — * `C` - Checking
* `S` - Savings
* `X` - Credit Card
- `id` (path, required)
- `ordering` (query, optional) — Which field to use when ordering the results.
- `page` (query, optional) — A page number within the paginated result set.
- `page_size` (query, optional) — Number of results to return per page.

**Response 200:** 

- **`count`** (`integer`) *(required)*
- **`next`** (`string`)
- **`previous`** (`string`)
- **`results`** (`array`) *(required)*

#### `POST /api/v1/bank-accounts/{id}/invitations/{token}/cancel/`

**Operation:** `bank_accounts_invitations_cancel_create`

Cancel a pending co-ownership invitation by token. Only the user who sent the invitation may cancel it.

**Parameters:**

- `id` (path, required)
- `token` (path, required) — The invitation's opaque token.

**Response 200:** No response body

#### `POST /api/v1/bank-accounts/{id}/invite/`

**Operation:** `bank_accounts_invite_create`

Send a co-ownership invitation to the given email address. If no mibudge account exists for that address, an inactive placeholder account is created; the invitee sets their password after accepting. Returns 409 if the address is already an owner or a pending invitation already exists; 429 if too many invitations have been sent to this address for this account in the rolling window.

**Parameters:**

- `id` (path, required)

**Request Body** (`application/json`):

- **`invitee_email`** (`string`) *(required)*

**Request Body** (`application/x-www-form-urlencoded`):

- **`invitee_email`** (`string`) *(required)*

**Request Body** (`multipart/form-data`):

- **`invitee_email`** (`string`) *(required)*

**Response 201:** No response body

#### `POST /api/v1/bank-accounts/{id}/mark-imported/`

**Operation:** `bank_accounts_mark_imported_create`

Record that a transaction import has been completed for this account.  Sets last_imported_at to now and advances last_posted_through to the supplied date (never regresses an existing value).  Body: {"last_posted_through": "YYYY-MM-DD"}.

**Parameters:**

- `id` (path, required)

**Request Body** (`application/json`):

- **`last_posted_through`** (`string`) *(required)*

**Response 200:** 

- **`id`** (`string`) *(required, read-only)*
- **`name`** (`string`) *(required)*
- **`bank`** (`string`) *(required)*
- **`owners`** (`array`) *(required, read-only)*
- **`account_type`** (`string`) — * `C` - Checking
* `S` - Savings
* `X` - Credit Card Enum: ['C', 'S', 'X']
- **`account_number`** (`string`)
- **`currency`** (`string`) — ISO 4217 currency code (e.g. USD, EUR, GBP).
- **`posted_balance`** (`string`)
- **`posted_balance_currency`** (`string`) *(required, read-only)*
- **`available_balance`** (`string`)
- **`available_balance_currency`** (`string`) *(required, read-only)*
- **`unallocated_budget`** (`string`) *(required, read-only)*
- **`auto_funding_enabled`** (`boolean`) — When enabled (the default), scheduled funding and recurrence events run automatically for this account.  Disable to opt out of automation and drive funding entirely from the 'Run funding now' button.
- **`last_imported_at`** (`string`) *(required, read-only)* — Wall-clock time of the most recent completed import for this account.
- **`last_posted_through`** (`string`) *(required, read-only)* — Latest posted_date seen in the most recent import batch. The funding engine will not process events dated after this value.
- **`created_at`** (`string`) *(required, read-only)*
- **`modified_at`** (`string`) *(required, read-only)*

#### `POST /api/v1/bank-accounts/{id}/run-funding/`

**Operation:** `bank_accounts_run_funding_create`

Run the funding engine for this account immediately.  Processes all due fund and recurrence events up to `as_of` (defaults to today) and returns a summary of what happened.  Pass `as_of` when calling between import batches so the engine only sees events up to that batch boundary date.

**Parameters:**

- `id` (path, required)

**Request Body** (`application/json`):

- **`as_of`** (`string`) — Upper bound for event enumeration (YYYY-MM-DD). Defaults to today.

**Response 200:** Funding run result.

- **`transfers`** (`integer`)
- **`occurrences_completed`** (`integer`)
- **`occurrences_partial`** (`integer`)
- **`warnings`** (`array`)
- **`skipped_budgets`** (`array`)

**Response 409:** Either another worker is currently processing this account (lock held), or there is nothing due or outstanding to run as of the supplied date.

#### `POST /api/v1/bank-accounts/{id}/sync-scrape/`

**Operation:** `bank_accounts_sync_scrape_create`

Reconcile this account against a fresh snapshot from a live bank scraper.  All existing pending transactions on the account are deleted, posted transactions from the scrape are de-duplicated against the database, and any new posted/pending rows are inserted in the order the scraper supplies (newest-first).  Per-transaction running balance snapshots and the unallocated-budget allocation snapshots are recomputed before the request returns.  Runs atomically under the account + unallocated-budget locks; on any error the database is unchanged.

**Parameters:**

- `id` (path, required)

**Request Body** (`application/json`):

- **`scraped_at`** (`string`) *(required)*
- **`ending_balance`** (`string`) *(required)*
- **`transactions`** (`array`) *(required)*

**Request Body** (`application/x-www-form-urlencoded`):

- **`scraped_at`** (`string`) *(required)*
- **`ending_balance`** (`string`) *(required)*
- **`transactions`** (`array`) *(required)*

**Request Body** (`multipart/form-data`):

- **`scraped_at`** (`string`) *(required)*
- **`ending_balance`** (`string`) *(required)*
- **`transactions`** (`array`) *(required)*

**Response 200:** 

- **`deleted_pending`** (`integer`) *(required)*
- **`inserted_posted`** (`integer`) *(required)*
- **`skipped_posted`** (`integer`) *(required)*
- **`inserted_pending`** (`integer`) *(required)*
- **`balance_mismatch`** (`string`) *(required)*
- **`posting_order_mismatches`** (`array`) *(required)*
- **`last_posted_through`** (`string`) *(required)*
- **`new_transaction_ids`** (`array`) *(required)*
- **`details_needed`** (`array`) *(required)*

#### `POST /api/v1/bank-accounts/{id}/transaction-details/`

**Operation:** `bank_accounts_transaction_details_create`

Apply per-transaction detail records (merchant name, location, MCC, the bank's category hint, virtual card number) fetched by a live scraper to posted transactions on this account.  Each raw details dict is stored verbatim on its transaction; merchant columns are extracted, the category hint seeds the transaction's category (and its unassigned allocations) when NULL, and the display description is recomposed on first enrichment unless the user has edited it.  Rows already enriched are skipped unless `overwrite` is true; pending rows are always skipped.  Per-item outcomes are returned in submission order.

**Parameters:**

- `id` (path, required)

**Request Body** (`application/json`):

- **`overwrite`** (`boolean`)
- **`details`** (`array`) *(required)*

**Request Body** (`application/x-www-form-urlencoded`):

- **`overwrite`** (`boolean`)
- **`details`** (`array`) *(required)*

**Request Body** (`multipart/form-data`):

- **`overwrite`** (`boolean`)
- **`details`** (`array`) *(required)*

**Response 200:** 

- **`applied`** (`integer`) *(required)*
- **`skipped_has_details`** (`integer`) *(required)*
- **`skipped_pending`** (`integer`) *(required)*
- **`not_found`** (`integer`) *(required)*
- **`results`** (`array`) *(required)*

### banks

#### `GET /api/v1/banks/`

**Operation:** `banks_list`

Return all banks in the system. Banks are shared reference data managed through the admin -- any authenticated user can list and retrieve them.

**Parameters:**

- `ordering` (query, optional) — Which field to use when ordering the results.
- `page` (query, optional) — A page number within the paginated result set.
- `page_size` (query, optional) — Number of results to return per page.

**Response 200:** 

- **`count`** (`integer`) *(required)*
- **`next`** (`string`)
- **`previous`** (`string`)
- **`results`** (`array`) *(required)*

#### `GET /api/v1/banks/{id}/`

**Operation:** `banks_retrieve`

Return a single bank by UUID.

**Parameters:**

- `id` (path, required)

**Response 200:** 

- **`id`** (`string`) *(required, read-only)*
- **`name`** (`string`) *(required, read-only)*
- **`routing_number`** (`string`) *(required, read-only)*
- **`default_currency`** (`string`) *(required, read-only)* — ISO 4217 currency code (e.g. USD, EUR, GBP).
- **`created_at`** (`string`) *(required, read-only)*
- **`modified_at`** (`string`) *(required, read-only)*

### budgets

#### `GET /api/v1/budgets/`

**Operation:** `budgets_list`

Return budgets belonging to the authenticated user's accounts. Filterable by bank_account, budget_type, archived, and paused. Searchable by name. Orderable by name, created_at, or balance.

**Parameters:**

- `archived` (query, optional)
- `bank_account` (query, optional)
- `budget_type` (query, optional) — * `G` - Goal
* `R` - Recurring
* `A` - Associated Fill-up Goal
* `C` - Capped
- `ordering` (query, optional) — Which field to use when ordering the results.
- `page` (query, optional) — A page number within the paginated result set.
- `page_size` (query, optional) — Number of results to return per page.
- `paused` (query, optional)
- `search` (query, optional) — A search term.

**Response 200:** 

- **`count`** (`integer`) *(required)*
- **`next`** (`string`)
- **`previous`** (`string`)
- **`results`** (`array`) *(required)*

#### `POST /api/v1/budgets/`

**Operation:** `budgets_create`

Create a new budget under a bank account. Required: name, bank_account (UUID), budget_type, funding_type, and target_balance. The bank_account and budget_type are immutable after creation. Balance is managed by signals and is always read-only.

**Request Body** (`application/json`):

- **`name`** (`string`) *(required)*
- **`bank_account`** (`string`) *(required)*
- **`target_balance`** (`string`) *(required)*
- **`funding_amount`** (`string`)
- **`budget_type`** (`string`) — * `G` - Goal
* `R` - Recurring
* `A` - Associated Fill-up Goal
* `C` - Capped Enum: ['G', 'R', 'A', 'C']
- **`funding_type`** (`string`) — * `D` - Target Date
* `F` - Fixed Amount Enum: ['D', 'F']
- **`target_date`** (`string`)
- **`fillup_goal`** (`string`)
- **`paused`** (`boolean`) — A paused budget does not get automatically funded on its schedule.
- **`funding_schedule`** (`string`)
- **`recurrence_schedule`** (`string`) — Refresh cycle for Recurring budgets.  Restricted grammar: a single RRULE whose FREQ is WEEKLY, MONTHLY, or YEARLY with an optional INTERVAL, plus an optional DTSTART that anchors the day the cycle refreshes on (e.g. 'DTSTART:20260708T000000Z RRULE:FREQ=MONTHLY' refreshes on the 8th of every month).  BY* parts, COUNT, UNTIL, and exception rules/dates are rejected -- the anchor date is the only day-of-cycle control.  The funding_schedule field is not restricted this way.
- **`memo`** (`string`)
- **`auto_spend`** (``) — List of matcher strings; currently transaction-category full names ('{group} : {name}').  Spend matching an entry is auto-routed to this budget.

**Request Body** (`application/x-www-form-urlencoded`):

- **`name`** (`string`) *(required)*
- **`bank_account`** (`string`) *(required)*
- **`target_balance`** (`string`) *(required)*
- **`funding_amount`** (`string`)
- **`budget_type`** (`string`) — * `G` - Goal
* `R` - Recurring
* `A` - Associated Fill-up Goal
* `C` - Capped Enum: ['G', 'R', 'A', 'C']
- **`funding_type`** (`string`) — * `D` - Target Date
* `F` - Fixed Amount Enum: ['D', 'F']
- **`target_date`** (`string`)
- **`fillup_goal`** (`string`)
- **`paused`** (`boolean`) — A paused budget does not get automatically funded on its schedule.
- **`funding_schedule`** (`string`)
- **`recurrence_schedule`** (`string`) — Refresh cycle for Recurring budgets.  Restricted grammar: a single RRULE whose FREQ is WEEKLY, MONTHLY, or YEARLY with an optional INTERVAL, plus an optional DTSTART that anchors the day the cycle refreshes on (e.g. 'DTSTART:20260708T000000Z RRULE:FREQ=MONTHLY' refreshes on the 8th of every month).  BY* parts, COUNT, UNTIL, and exception rules/dates are rejected -- the anchor date is the only day-of-cycle control.  The funding_schedule field is not restricted this way.
- **`memo`** (`string`)
- **`auto_spend`** (``) — List of matcher strings; currently transaction-category full names ('{group} : {name}').  Spend matching an entry is auto-routed to this budget.

**Request Body** (`multipart/form-data`):

- **`name`** (`string`) *(required)*
- **`bank_account`** (`string`) *(required)*
- **`target_balance`** (`string`) *(required)*
- **`funding_amount`** (`string`)
- **`budget_type`** (`string`) — * `G` - Goal
* `R` - Recurring
* `A` - Associated Fill-up Goal
* `C` - Capped Enum: ['G', 'R', 'A', 'C']
- **`funding_type`** (`string`) — * `D` - Target Date
* `F` - Fixed Amount Enum: ['D', 'F']
- **`target_date`** (`string`)
- **`fillup_goal`** (`string`)
- **`paused`** (`boolean`) — A paused budget does not get automatically funded on its schedule.
- **`funding_schedule`** (`string`)
- **`recurrence_schedule`** (`string`) — Refresh cycle for Recurring budgets.  Restricted grammar: a single RRULE whose FREQ is WEEKLY, MONTHLY, or YEARLY with an optional INTERVAL, plus an optional DTSTART that anchors the day the cycle refreshes on (e.g. 'DTSTART:20260708T000000Z RRULE:FREQ=MONTHLY' refreshes on the 8th of every month).  BY* parts, COUNT, UNTIL, and exception rules/dates are rejected -- the anchor date is the only day-of-cycle control.  The funding_schedule field is not restricted this way.
- **`memo`** (`string`)
- **`auto_spend`** (``) — List of matcher strings; currently transaction-category full names ('{group} : {name}').  Spend matching an entry is auto-routed to this budget.

**Response 201:** 

- **`id`** (`string`) *(required, read-only)*
- **`name`** (`string`) *(required)*
- **`bank_account`** (`string`) *(required)*
- **`balance`** (`string`) *(required, read-only)*
- **`balance_currency`** (`string`) *(required, read-only)*
- **`funded_amount`** (`string`) *(required, read-only)* — For Goal budgets: running net of all ITX credits minus debits. Unused for other types.
- **`funded_amount_currency`** (`string`) *(required, read-only)*
- **`target_balance`** (`string`) *(required)*
- **`target_balance_currency`** (`string`) *(required, read-only)*
- **`funding_amount`** (`string`)
- **`funding_amount_currency`** (`string`) *(required, read-only)*
- **`budget_type`** (`string`) — * `G` - Goal
* `R` - Recurring
* `A` - Associated Fill-up Goal
* `C` - Capped Enum: ['G', 'R', 'A', 'C']
- **`funding_type`** (`string`) — * `D` - Target Date
* `F` - Fixed Amount Enum: ['D', 'F']
- **`target_date`** (`string`)
- **`fillup_goal`** (`string`)
- **`archived`** (`boolean`) *(required, read-only)*
- **`archived_at`** (`string`) *(required, read-only)*
- **`complete`** (`boolean`) *(required, read-only)* — True when this budget has reached its target and should not be funded further.  Managed by signals and funding tasks; do not set manually.
- **`paused`** (`boolean`) — A paused budget does not get automatically funded on its schedule.
- **`funding_schedule`** (`string`)
- **`recurrence_schedule`** (`string`) — Refresh cycle for Recurring budgets.  Restricted grammar: a single RRULE whose FREQ is WEEKLY, MONTHLY, or YEARLY with an optional INTERVAL, plus an optional DTSTART that anchors the day the cycle refreshes on (e.g. 'DTSTART:20260708T000000Z RRULE:FREQ=MONTHLY' refreshes on the 8th of every month).  BY* parts, COUNT, UNTIL, and exception rules/dates are rejected -- the anchor date is the only day-of-cycle control.  The funding_schedule field is not restricted this way.
- **`memo`** (`string`)
- **`auto_spend`** (``) — List of matcher strings; currently transaction-category full names ('{group} : {name}').  Spend matching an entry is auto-routed to this budget.
- **`next_funding`** (`object`) *(required, read-only)* — Return the next scheduled funding event for this budget, or null.

Args:
    obj: The Budget instance being serialized.

Returns:
    Dict with 'date', 'amount', 'amount_currency', or None.
- **`next_recurrence`** (`string`) *(required, read-only)* — Return the date of the next recurrence (refresh) event, or null.

The recurrence_schedule's DTSTART is only the rule's anchor;
this field is the actual upcoming refresh date (first
occurrence after last_recurrence_on).  Only Recurring budgets
have one.

Args:
    obj: The Budget instance being serialized.

Returns:
    ISO date string, or None.
- **`funding_pace`** (``) *(required, read-only)*
- **`created_at`** (`string`) *(required, read-only)*
- **`modified_at`** (`string`) *(required, read-only)*

#### `GET /api/v1/budgets/{id}/`

**Operation:** `budgets_retrieve`

Return a single budget by UUID.

**Parameters:**

- `id` (path, required)

**Response 200:** 

- **`id`** (`string`) *(required, read-only)*
- **`name`** (`string`) *(required)*
- **`bank_account`** (`string`) *(required)*
- **`balance`** (`string`) *(required, read-only)*
- **`balance_currency`** (`string`) *(required, read-only)*
- **`funded_amount`** (`string`) *(required, read-only)* — For Goal budgets: running net of all ITX credits minus debits. Unused for other types.
- **`funded_amount_currency`** (`string`) *(required, read-only)*
- **`target_balance`** (`string`) *(required)*
- **`target_balance_currency`** (`string`) *(required, read-only)*
- **`funding_amount`** (`string`)
- **`funding_amount_currency`** (`string`) *(required, read-only)*
- **`budget_type`** (`string`) — * `G` - Goal
* `R` - Recurring
* `A` - Associated Fill-up Goal
* `C` - Capped Enum: ['G', 'R', 'A', 'C']
- **`funding_type`** (`string`) — * `D` - Target Date
* `F` - Fixed Amount Enum: ['D', 'F']
- **`target_date`** (`string`)
- **`fillup_goal`** (`string`)
- **`archived`** (`boolean`) *(required, read-only)*
- **`archived_at`** (`string`) *(required, read-only)*
- **`complete`** (`boolean`) *(required, read-only)* — True when this budget has reached its target and should not be funded further.  Managed by signals and funding tasks; do not set manually.
- **`paused`** (`boolean`) — A paused budget does not get automatically funded on its schedule.
- **`funding_schedule`** (`string`)
- **`recurrence_schedule`** (`string`) — Refresh cycle for Recurring budgets.  Restricted grammar: a single RRULE whose FREQ is WEEKLY, MONTHLY, or YEARLY with an optional INTERVAL, plus an optional DTSTART that anchors the day the cycle refreshes on (e.g. 'DTSTART:20260708T000000Z RRULE:FREQ=MONTHLY' refreshes on the 8th of every month).  BY* parts, COUNT, UNTIL, and exception rules/dates are rejected -- the anchor date is the only day-of-cycle control.  The funding_schedule field is not restricted this way.
- **`memo`** (`string`)
- **`auto_spend`** (``) — List of matcher strings; currently transaction-category full names ('{group} : {name}').  Spend matching an entry is auto-routed to this budget.
- **`next_funding`** (`object`) *(required, read-only)* — Return the next scheduled funding event for this budget, or null.

Args:
    obj: The Budget instance being serialized.

Returns:
    Dict with 'date', 'amount', 'amount_currency', or None.
- **`next_recurrence`** (`string`) *(required, read-only)* — Return the date of the next recurrence (refresh) event, or null.

The recurrence_schedule's DTSTART is only the rule's anchor;
this field is the actual upcoming refresh date (first
occurrence after last_recurrence_on).  Only Recurring budgets
have one.

Args:
    obj: The Budget instance being serialized.

Returns:
    ISO date string, or None.
- **`funding_pace`** (``) *(required, read-only)*
- **`created_at`** (`string`) *(required, read-only)*
- **`modified_at`** (`string`) *(required, read-only)*

#### `PUT /api/v1/budgets/{id}/`

**Operation:** `budgets_update`

Full update of a budget. bank_account and budget_type are immutable. The unallocated budget cannot be renamed.

**Parameters:**

- `id` (path, required)

**Request Body** (`application/json`):

- **`name`** (`string`) *(required)*
- **`bank_account`** (`string`) *(required)*
- **`target_balance`** (`string`) *(required)*
- **`funding_amount`** (`string`)
- **`budget_type`** (`string`) — * `G` - Goal
* `R` - Recurring
* `A` - Associated Fill-up Goal
* `C` - Capped Enum: ['G', 'R', 'A', 'C']
- **`funding_type`** (`string`) — * `D` - Target Date
* `F` - Fixed Amount Enum: ['D', 'F']
- **`target_date`** (`string`)
- **`fillup_goal`** (`string`)
- **`paused`** (`boolean`) — A paused budget does not get automatically funded on its schedule.
- **`funding_schedule`** (`string`)
- **`recurrence_schedule`** (`string`) — Refresh cycle for Recurring budgets.  Restricted grammar: a single RRULE whose FREQ is WEEKLY, MONTHLY, or YEARLY with an optional INTERVAL, plus an optional DTSTART that anchors the day the cycle refreshes on (e.g. 'DTSTART:20260708T000000Z RRULE:FREQ=MONTHLY' refreshes on the 8th of every month).  BY* parts, COUNT, UNTIL, and exception rules/dates are rejected -- the anchor date is the only day-of-cycle control.  The funding_schedule field is not restricted this way.
- **`memo`** (`string`)
- **`auto_spend`** (``) — List of matcher strings; currently transaction-category full names ('{group} : {name}').  Spend matching an entry is auto-routed to this budget.

**Request Body** (`application/x-www-form-urlencoded`):

- **`name`** (`string`) *(required)*
- **`bank_account`** (`string`) *(required)*
- **`target_balance`** (`string`) *(required)*
- **`funding_amount`** (`string`)
- **`budget_type`** (`string`) — * `G` - Goal
* `R` - Recurring
* `A` - Associated Fill-up Goal
* `C` - Capped Enum: ['G', 'R', 'A', 'C']
- **`funding_type`** (`string`) — * `D` - Target Date
* `F` - Fixed Amount Enum: ['D', 'F']
- **`target_date`** (`string`)
- **`fillup_goal`** (`string`)
- **`paused`** (`boolean`) — A paused budget does not get automatically funded on its schedule.
- **`funding_schedule`** (`string`)
- **`recurrence_schedule`** (`string`) — Refresh cycle for Recurring budgets.  Restricted grammar: a single RRULE whose FREQ is WEEKLY, MONTHLY, or YEARLY with an optional INTERVAL, plus an optional DTSTART that anchors the day the cycle refreshes on (e.g. 'DTSTART:20260708T000000Z RRULE:FREQ=MONTHLY' refreshes on the 8th of every month).  BY* parts, COUNT, UNTIL, and exception rules/dates are rejected -- the anchor date is the only day-of-cycle control.  The funding_schedule field is not restricted this way.
- **`memo`** (`string`)
- **`auto_spend`** (``) — List of matcher strings; currently transaction-category full names ('{group} : {name}').  Spend matching an entry is auto-routed to this budget.

**Request Body** (`multipart/form-data`):

- **`name`** (`string`) *(required)*
- **`bank_account`** (`string`) *(required)*
- **`target_balance`** (`string`) *(required)*
- **`funding_amount`** (`string`)
- **`budget_type`** (`string`) — * `G` - Goal
* `R` - Recurring
* `A` - Associated Fill-up Goal
* `C` - Capped Enum: ['G', 'R', 'A', 'C']
- **`funding_type`** (`string`) — * `D` - Target Date
* `F` - Fixed Amount Enum: ['D', 'F']
- **`target_date`** (`string`)
- **`fillup_goal`** (`string`)
- **`paused`** (`boolean`) — A paused budget does not get automatically funded on its schedule.
- **`funding_schedule`** (`string`)
- **`recurrence_schedule`** (`string`) — Refresh cycle for Recurring budgets.  Restricted grammar: a single RRULE whose FREQ is WEEKLY, MONTHLY, or YEARLY with an optional INTERVAL, plus an optional DTSTART that anchors the day the cycle refreshes on (e.g. 'DTSTART:20260708T000000Z RRULE:FREQ=MONTHLY' refreshes on the 8th of every month).  BY* parts, COUNT, UNTIL, and exception rules/dates are rejected -- the anchor date is the only day-of-cycle control.  The funding_schedule field is not restricted this way.
- **`memo`** (`string`)
- **`auto_spend`** (``) — List of matcher strings; currently transaction-category full names ('{group} : {name}').  Spend matching an entry is auto-routed to this budget.

**Response 200:** 

- **`id`** (`string`) *(required, read-only)*
- **`name`** (`string`) *(required)*
- **`bank_account`** (`string`) *(required)*
- **`balance`** (`string`) *(required, read-only)*
- **`balance_currency`** (`string`) *(required, read-only)*
- **`funded_amount`** (`string`) *(required, read-only)* — For Goal budgets: running net of all ITX credits minus debits. Unused for other types.
- **`funded_amount_currency`** (`string`) *(required, read-only)*
- **`target_balance`** (`string`) *(required)*
- **`target_balance_currency`** (`string`) *(required, read-only)*
- **`funding_amount`** (`string`)
- **`funding_amount_currency`** (`string`) *(required, read-only)*
- **`budget_type`** (`string`) — * `G` - Goal
* `R` - Recurring
* `A` - Associated Fill-up Goal
* `C` - Capped Enum: ['G', 'R', 'A', 'C']
- **`funding_type`** (`string`) — * `D` - Target Date
* `F` - Fixed Amount Enum: ['D', 'F']
- **`target_date`** (`string`)
- **`fillup_goal`** (`string`)
- **`archived`** (`boolean`) *(required, read-only)*
- **`archived_at`** (`string`) *(required, read-only)*
- **`complete`** (`boolean`) *(required, read-only)* — True when this budget has reached its target and should not be funded further.  Managed by signals and funding tasks; do not set manually.
- **`paused`** (`boolean`) — A paused budget does not get automatically funded on its schedule.
- **`funding_schedule`** (`string`)
- **`recurrence_schedule`** (`string`) — Refresh cycle for Recurring budgets.  Restricted grammar: a single RRULE whose FREQ is WEEKLY, MONTHLY, or YEARLY with an optional INTERVAL, plus an optional DTSTART that anchors the day the cycle refreshes on (e.g. 'DTSTART:20260708T000000Z RRULE:FREQ=MONTHLY' refreshes on the 8th of every month).  BY* parts, COUNT, UNTIL, and exception rules/dates are rejected -- the anchor date is the only day-of-cycle control.  The funding_schedule field is not restricted this way.
- **`memo`** (`string`)
- **`auto_spend`** (``) — List of matcher strings; currently transaction-category full names ('{group} : {name}').  Spend matching an entry is auto-routed to this budget.
- **`next_funding`** (`object`) *(required, read-only)* — Return the next scheduled funding event for this budget, or null.

Args:
    obj: The Budget instance being serialized.

Returns:
    Dict with 'date', 'amount', 'amount_currency', or None.
- **`next_recurrence`** (`string`) *(required, read-only)* — Return the date of the next recurrence (refresh) event, or null.

The recurrence_schedule's DTSTART is only the rule's anchor;
this field is the actual upcoming refresh date (first
occurrence after last_recurrence_on).  Only Recurring budgets
have one.

Args:
    obj: The Budget instance being serialized.

Returns:
    ISO date string, or None.
- **`funding_pace`** (``) *(required, read-only)*
- **`created_at`** (`string`) *(required, read-only)*
- **`modified_at`** (`string`) *(required, read-only)*

#### `PATCH /api/v1/budgets/{id}/`

**Operation:** `budgets_partial_update`

Partial update of a budget. bank_account and budget_type are immutable. The unallocated budget cannot be renamed.

**Parameters:**

- `id` (path, required)

**Request Body** (`application/json`):

- **`name`** (`string`)
- **`bank_account`** (`string`)
- **`target_balance`** (`string`)
- **`funding_amount`** (`string`)
- **`budget_type`** (`string`) — * `G` - Goal
* `R` - Recurring
* `A` - Associated Fill-up Goal
* `C` - Capped Enum: ['G', 'R', 'A', 'C']
- **`funding_type`** (`string`) — * `D` - Target Date
* `F` - Fixed Amount Enum: ['D', 'F']
- **`target_date`** (`string`)
- **`fillup_goal`** (`string`)
- **`paused`** (`boolean`) — A paused budget does not get automatically funded on its schedule.
- **`funding_schedule`** (`string`)
- **`recurrence_schedule`** (`string`) — Refresh cycle for Recurring budgets.  Restricted grammar: a single RRULE whose FREQ is WEEKLY, MONTHLY, or YEARLY with an optional INTERVAL, plus an optional DTSTART that anchors the day the cycle refreshes on (e.g. 'DTSTART:20260708T000000Z RRULE:FREQ=MONTHLY' refreshes on the 8th of every month).  BY* parts, COUNT, UNTIL, and exception rules/dates are rejected -- the anchor date is the only day-of-cycle control.  The funding_schedule field is not restricted this way.
- **`memo`** (`string`)
- **`auto_spend`** (``) — List of matcher strings; currently transaction-category full names ('{group} : {name}').  Spend matching an entry is auto-routed to this budget.

**Request Body** (`application/x-www-form-urlencoded`):

- **`name`** (`string`)
- **`bank_account`** (`string`)
- **`target_balance`** (`string`)
- **`funding_amount`** (`string`)
- **`budget_type`** (`string`) — * `G` - Goal
* `R` - Recurring
* `A` - Associated Fill-up Goal
* `C` - Capped Enum: ['G', 'R', 'A', 'C']
- **`funding_type`** (`string`) — * `D` - Target Date
* `F` - Fixed Amount Enum: ['D', 'F']
- **`target_date`** (`string`)
- **`fillup_goal`** (`string`)
- **`paused`** (`boolean`) — A paused budget does not get automatically funded on its schedule.
- **`funding_schedule`** (`string`)
- **`recurrence_schedule`** (`string`) — Refresh cycle for Recurring budgets.  Restricted grammar: a single RRULE whose FREQ is WEEKLY, MONTHLY, or YEARLY with an optional INTERVAL, plus an optional DTSTART that anchors the day the cycle refreshes on (e.g. 'DTSTART:20260708T000000Z RRULE:FREQ=MONTHLY' refreshes on the 8th of every month).  BY* parts, COUNT, UNTIL, and exception rules/dates are rejected -- the anchor date is the only day-of-cycle control.  The funding_schedule field is not restricted this way.
- **`memo`** (`string`)
- **`auto_spend`** (``) — List of matcher strings; currently transaction-category full names ('{group} : {name}').  Spend matching an entry is auto-routed to this budget.

**Request Body** (`multipart/form-data`):

- **`name`** (`string`)
- **`bank_account`** (`string`)
- **`target_balance`** (`string`)
- **`funding_amount`** (`string`)
- **`budget_type`** (`string`) — * `G` - Goal
* `R` - Recurring
* `A` - Associated Fill-up Goal
* `C` - Capped Enum: ['G', 'R', 'A', 'C']
- **`funding_type`** (`string`) — * `D` - Target Date
* `F` - Fixed Amount Enum: ['D', 'F']
- **`target_date`** (`string`)
- **`fillup_goal`** (`string`)
- **`paused`** (`boolean`) — A paused budget does not get automatically funded on its schedule.
- **`funding_schedule`** (`string`)
- **`recurrence_schedule`** (`string`) — Refresh cycle for Recurring budgets.  Restricted grammar: a single RRULE whose FREQ is WEEKLY, MONTHLY, or YEARLY with an optional INTERVAL, plus an optional DTSTART that anchors the day the cycle refreshes on (e.g. 'DTSTART:20260708T000000Z RRULE:FREQ=MONTHLY' refreshes on the 8th of every month).  BY* parts, COUNT, UNTIL, and exception rules/dates are rejected -- the anchor date is the only day-of-cycle control.  The funding_schedule field is not restricted this way.
- **`memo`** (`string`)
- **`auto_spend`** (``) — List of matcher strings; currently transaction-category full names ('{group} : {name}').  Spend matching an entry is auto-routed to this budget.

**Response 200:** 

- **`id`** (`string`) *(required, read-only)*
- **`name`** (`string`) *(required)*
- **`bank_account`** (`string`) *(required)*
- **`balance`** (`string`) *(required, read-only)*
- **`balance_currency`** (`string`) *(required, read-only)*
- **`funded_amount`** (`string`) *(required, read-only)* — For Goal budgets: running net of all ITX credits minus debits. Unused for other types.
- **`funded_amount_currency`** (`string`) *(required, read-only)*
- **`target_balance`** (`string`) *(required)*
- **`target_balance_currency`** (`string`) *(required, read-only)*
- **`funding_amount`** (`string`)
- **`funding_amount_currency`** (`string`) *(required, read-only)*
- **`budget_type`** (`string`) — * `G` - Goal
* `R` - Recurring
* `A` - Associated Fill-up Goal
* `C` - Capped Enum: ['G', 'R', 'A', 'C']
- **`funding_type`** (`string`) — * `D` - Target Date
* `F` - Fixed Amount Enum: ['D', 'F']
- **`target_date`** (`string`)
- **`fillup_goal`** (`string`)
- **`archived`** (`boolean`) *(required, read-only)*
- **`archived_at`** (`string`) *(required, read-only)*
- **`complete`** (`boolean`) *(required, read-only)* — True when this budget has reached its target and should not be funded further.  Managed by signals and funding tasks; do not set manually.
- **`paused`** (`boolean`) — A paused budget does not get automatically funded on its schedule.
- **`funding_schedule`** (`string`)
- **`recurrence_schedule`** (`string`) — Refresh cycle for Recurring budgets.  Restricted grammar: a single RRULE whose FREQ is WEEKLY, MONTHLY, or YEARLY with an optional INTERVAL, plus an optional DTSTART that anchors the day the cycle refreshes on (e.g. 'DTSTART:20260708T000000Z RRULE:FREQ=MONTHLY' refreshes on the 8th of every month).  BY* parts, COUNT, UNTIL, and exception rules/dates are rejected -- the anchor date is the only day-of-cycle control.  The funding_schedule field is not restricted this way.
- **`memo`** (`string`)
- **`auto_spend`** (``) — List of matcher strings; currently transaction-category full names ('{group} : {name}').  Spend matching an entry is auto-routed to this budget.
- **`next_funding`** (`object`) *(required, read-only)* — Return the next scheduled funding event for this budget, or null.

Args:
    obj: The Budget instance being serialized.

Returns:
    Dict with 'date', 'amount', 'amount_currency', or None.
- **`next_recurrence`** (`string`) *(required, read-only)* — Return the date of the next recurrence (refresh) event, or null.

The recurrence_schedule's DTSTART is only the rule's anchor;
this field is the actual upcoming refresh date (first
occurrence after last_recurrence_on).  Only Recurring budgets
have one.

Args:
    obj: The Budget instance being serialized.

Returns:
    ISO date string, or None.
- **`funding_pace`** (``) *(required, read-only)*
- **`created_at`** (`string`) *(required, read-only)*
- **`modified_at`** (`string`) *(required, read-only)*

#### `DELETE /api/v1/budgets/{id}/`

**Operation:** `budgets_destroy`

Delete a budget. The unallocated budget cannot be deleted (403). A budget with existing transaction allocations cannot be deleted (400) -- archive it instead.

**Parameters:**

- `id` (path, required)

**Response 204:** No response body

#### `POST /api/v1/budgets/{id}/archive/`

**Operation:** `budgets_archive_create`

Archive a budget. Any remaining balance is transferred to the account's unallocated budget. If the budget has an associated fill-up goal, that budget is also archived and its balance moved to unallocated. The unallocated budget cannot be archived.

**Parameters:**

- `id` (path, required)

**Request Body** (`application/json`):

- **`name`** (`string`) *(required)*
- **`bank_account`** (`string`) *(required)*
- **`target_balance`** (`string`) *(required)*
- **`funding_amount`** (`string`)
- **`budget_type`** (`string`) — * `G` - Goal
* `R` - Recurring
* `A` - Associated Fill-up Goal
* `C` - Capped Enum: ['G', 'R', 'A', 'C']
- **`funding_type`** (`string`) — * `D` - Target Date
* `F` - Fixed Amount Enum: ['D', 'F']
- **`target_date`** (`string`)
- **`fillup_goal`** (`string`)
- **`paused`** (`boolean`) — A paused budget does not get automatically funded on its schedule.
- **`funding_schedule`** (`string`)
- **`recurrence_schedule`** (`string`) — Refresh cycle for Recurring budgets.  Restricted grammar: a single RRULE whose FREQ is WEEKLY, MONTHLY, or YEARLY with an optional INTERVAL, plus an optional DTSTART that anchors the day the cycle refreshes on (e.g. 'DTSTART:20260708T000000Z RRULE:FREQ=MONTHLY' refreshes on the 8th of every month).  BY* parts, COUNT, UNTIL, and exception rules/dates are rejected -- the anchor date is the only day-of-cycle control.  The funding_schedule field is not restricted this way.
- **`memo`** (`string`)
- **`auto_spend`** (``) — List of matcher strings; currently transaction-category full names ('{group} : {name}').  Spend matching an entry is auto-routed to this budget.

**Request Body** (`application/x-www-form-urlencoded`):

- **`name`** (`string`) *(required)*
- **`bank_account`** (`string`) *(required)*
- **`target_balance`** (`string`) *(required)*
- **`funding_amount`** (`string`)
- **`budget_type`** (`string`) — * `G` - Goal
* `R` - Recurring
* `A` - Associated Fill-up Goal
* `C` - Capped Enum: ['G', 'R', 'A', 'C']
- **`funding_type`** (`string`) — * `D` - Target Date
* `F` - Fixed Amount Enum: ['D', 'F']
- **`target_date`** (`string`)
- **`fillup_goal`** (`string`)
- **`paused`** (`boolean`) — A paused budget does not get automatically funded on its schedule.
- **`funding_schedule`** (`string`)
- **`recurrence_schedule`** (`string`) — Refresh cycle for Recurring budgets.  Restricted grammar: a single RRULE whose FREQ is WEEKLY, MONTHLY, or YEARLY with an optional INTERVAL, plus an optional DTSTART that anchors the day the cycle refreshes on (e.g. 'DTSTART:20260708T000000Z RRULE:FREQ=MONTHLY' refreshes on the 8th of every month).  BY* parts, COUNT, UNTIL, and exception rules/dates are rejected -- the anchor date is the only day-of-cycle control.  The funding_schedule field is not restricted this way.
- **`memo`** (`string`)
- **`auto_spend`** (``) — List of matcher strings; currently transaction-category full names ('{group} : {name}').  Spend matching an entry is auto-routed to this budget.

**Request Body** (`multipart/form-data`):

- **`name`** (`string`) *(required)*
- **`bank_account`** (`string`) *(required)*
- **`target_balance`** (`string`) *(required)*
- **`funding_amount`** (`string`)
- **`budget_type`** (`string`) — * `G` - Goal
* `R` - Recurring
* `A` - Associated Fill-up Goal
* `C` - Capped Enum: ['G', 'R', 'A', 'C']
- **`funding_type`** (`string`) — * `D` - Target Date
* `F` - Fixed Amount Enum: ['D', 'F']
- **`target_date`** (`string`)
- **`fillup_goal`** (`string`)
- **`paused`** (`boolean`) — A paused budget does not get automatically funded on its schedule.
- **`funding_schedule`** (`string`)
- **`recurrence_schedule`** (`string`) — Refresh cycle for Recurring budgets.  Restricted grammar: a single RRULE whose FREQ is WEEKLY, MONTHLY, or YEARLY with an optional INTERVAL, plus an optional DTSTART that anchors the day the cycle refreshes on (e.g. 'DTSTART:20260708T000000Z RRULE:FREQ=MONTHLY' refreshes on the 8th of every month).  BY* parts, COUNT, UNTIL, and exception rules/dates are rejected -- the anchor date is the only day-of-cycle control.  The funding_schedule field is not restricted this way.
- **`memo`** (`string`)
- **`auto_spend`** (``) — List of matcher strings; currently transaction-category full names ('{group} : {name}').  Spend matching an entry is auto-routed to this budget.

**Response 200:** 

- **`id`** (`string`) *(required, read-only)*
- **`name`** (`string`) *(required)*
- **`bank_account`** (`string`) *(required)*
- **`balance`** (`string`) *(required, read-only)*
- **`balance_currency`** (`string`) *(required, read-only)*
- **`funded_amount`** (`string`) *(required, read-only)* — For Goal budgets: running net of all ITX credits minus debits. Unused for other types.
- **`funded_amount_currency`** (`string`) *(required, read-only)*
- **`target_balance`** (`string`) *(required)*
- **`target_balance_currency`** (`string`) *(required, read-only)*
- **`funding_amount`** (`string`)
- **`funding_amount_currency`** (`string`) *(required, read-only)*
- **`budget_type`** (`string`) — * `G` - Goal
* `R` - Recurring
* `A` - Associated Fill-up Goal
* `C` - Capped Enum: ['G', 'R', 'A', 'C']
- **`funding_type`** (`string`) — * `D` - Target Date
* `F` - Fixed Amount Enum: ['D', 'F']
- **`target_date`** (`string`)
- **`fillup_goal`** (`string`)
- **`archived`** (`boolean`) *(required, read-only)*
- **`archived_at`** (`string`) *(required, read-only)*
- **`complete`** (`boolean`) *(required, read-only)* — True when this budget has reached its target and should not be funded further.  Managed by signals and funding tasks; do not set manually.
- **`paused`** (`boolean`) — A paused budget does not get automatically funded on its schedule.
- **`funding_schedule`** (`string`)
- **`recurrence_schedule`** (`string`) — Refresh cycle for Recurring budgets.  Restricted grammar: a single RRULE whose FREQ is WEEKLY, MONTHLY, or YEARLY with an optional INTERVAL, plus an optional DTSTART that anchors the day the cycle refreshes on (e.g. 'DTSTART:20260708T000000Z RRULE:FREQ=MONTHLY' refreshes on the 8th of every month).  BY* parts, COUNT, UNTIL, and exception rules/dates are rejected -- the anchor date is the only day-of-cycle control.  The funding_schedule field is not restricted this way.
- **`memo`** (`string`)
- **`auto_spend`** (``) — List of matcher strings; currently transaction-category full names ('{group} : {name}').  Spend matching an entry is auto-routed to this budget.
- **`next_funding`** (`object`) *(required, read-only)* — Return the next scheduled funding event for this budget, or null.

Args:
    obj: The Budget instance being serialized.

Returns:
    Dict with 'date', 'amount', 'amount_currency', or None.
- **`next_recurrence`** (`string`) *(required, read-only)* — Return the date of the next recurrence (refresh) event, or null.

The recurrence_schedule's DTSTART is only the rule's anchor;
this field is the actual upcoming refresh date (first
occurrence after last_recurrence_on).  Only Recurring budgets
have one.

Args:
    obj: The Budget instance being serialized.

Returns:
    ISO date string, or None.
- **`funding_pace`** (``) *(required, read-only)*
- **`created_at`** (`string`) *(required, read-only)*
- **`modified_at`** (`string`) *(required, read-only)*

### channel-preferences

#### `GET /api/v1/channel-preferences/`

**Operation:** `channel_preferences_list`

Return all notification channels with the authenticated user's delivery preferences. Channels without a stored preference fall back to DAILY_MORNING.

**Parameters:**

- `page` (query, optional) — A page number within the paginated result set.
- `page_size` (query, optional) — Number of results to return per page.

**Response 200:** 

- **`count`** (`integer`) *(required)*
- **`next`** (`string`)
- **`previous`** (`string`)
- **`results`** (`array`) *(required)*

#### `PATCH /api/v1/channel-preferences/{channel}/`

**Operation:** `channel_preferences_partial_update`

Set the digest_frequency for a notification channel. Returns 404 if the channel value is not valid.

**Parameters:**

- `channel` (path, required) — Channel identifier (e.g. 'email').

**Request Body** (`application/json`):

- **`digest_frequency`** (`string`) — * `daily_morning` - Once daily (morning, ~7 am)
* `daily_evening` - Once daily (evening, ~6 pm)
* `twice_daily` - Twice daily (morning + evening)
* `weekly_friday` - Weekly on Friday
* `weekly_saturday` - Weekly on Saturday
* `weekly_sunday` - Weekly on Sunday Enum: ['daily_morning', 'daily_evening', 'twice_daily', 'weekly_friday', 'weekly_saturday', 'weekly_sunday']

**Request Body** (`application/x-www-form-urlencoded`):

- **`digest_frequency`** (`string`) — * `daily_morning` - Once daily (morning, ~7 am)
* `daily_evening` - Once daily (evening, ~6 pm)
* `twice_daily` - Twice daily (morning + evening)
* `weekly_friday` - Weekly on Friday
* `weekly_saturday` - Weekly on Saturday
* `weekly_sunday` - Weekly on Sunday Enum: ['daily_morning', 'daily_evening', 'twice_daily', 'weekly_friday', 'weekly_saturday', 'weekly_sunday']

**Request Body** (`multipart/form-data`):

- **`digest_frequency`** (`string`) — * `daily_morning` - Once daily (morning, ~7 am)
* `daily_evening` - Once daily (evening, ~6 pm)
* `twice_daily` - Twice daily (morning + evening)
* `weekly_friday` - Weekly on Friday
* `weekly_saturday` - Weekly on Saturday
* `weekly_sunday` - Weekly on Sunday Enum: ['daily_morning', 'daily_evening', 'twice_daily', 'weekly_friday', 'weekly_saturday', 'weekly_sunday']

**Response 200:** 

- **`channel`** (`string`) *(required, read-only)*
- **`display_name`** (`string`) *(required, read-only)*
- **`digest_frequency`** (`string`) *(required)* — * `daily_morning` - Once daily (morning, ~7 am)
* `daily_evening` - Once daily (evening, ~6 pm)
* `twice_daily` - Twice daily (morning + evening)
* `weekly_friday` - Weekly on Friday
* `weekly_saturday` - Weekly on Saturday
* `weekly_sunday` - Weekly on Sunday Enum: ['daily_morning', 'daily_evening', 'twice_daily', 'weekly_friday', 'weekly_saturday', 'weekly_sunday']

### currencies

#### `GET /api/v1/currencies/`

**Operation:** `currencies_retrieve`

Return all ISO 4217 currency codes supported by the system, sorted by code. Each entry includes the code, English name, and numeric ISO 4217 code. Requires authentication.

**Response 200:** List of supported currencies.

### funding-occurrences

#### `GET /api/v1/funding-occurrences/`

**Operation:** `funding_occurrences_list`

Return funding event occurrences for budgets on accounts owned by the authenticated user.  Filterable by bank_account, budget, kind, status (multi-value), and scheduled_date range.  Orderable by scheduled_date or created_at.

**Parameters:**

- `bank_account` (query, optional)
- `budget` (query, optional)
- `date_from` (query, optional)
- `date_to` (query, optional)
- `kind` (query, optional) — Funding event discriminator: "fund" or "recur".  Stored as the EventKind string value; not exposed in user-facing forms so no choices= is set.

* `fund` - fund
* `recur` - recur
- `ordering` (query, optional) — Which field to use when ordering the results.
- `page` (query, optional) — A page number within the paginated result set.
- `page_size` (query, optional) — Number of results to return per page.
- `status` (query, optional) — * `PENDING` - Pending
* `PARTIAL` - Partial
* `COMPLETE` - Complete
* `SKIPPED` - Skipped

**Response 200:** 

- **`count`** (`integer`) *(required)*
- **`next`** (`string`)
- **`previous`** (`string`)
- **`results`** (`array`) *(required)*

#### `GET /api/v1/funding-occurrences/{id}/`

**Operation:** `funding_occurrences_retrieve`

Return a single funding event occurrence by UUID.

**Parameters:**

- `id` (path, required)

**Response 200:** 

- **`id`** (`string`) *(required, read-only)*
- **`budget`** (`string`) *(required, read-only)*
- **`kind`** (`string`) *(required, read-only)* — Funding event discriminator: "fund" or "recur".  Stored as the EventKind string value; not exposed in user-facing forms so no choices= is set.
- **`scheduled_date`** (`string`) *(required, read-only)* — Calendar date the event was scheduled to fire.
- **`status`** (``) *(required, read-only)*
- **`completed_at`** (`string`) *(required, read-only)* — Wall-clock time the occurrence reached COMPLETE.  Null while PENDING/PARTIAL/SKIPPED.
- **`created_at`** (`string`) *(required, read-only)*
- **`modified_at`** (`string`) *(required, read-only)*

### internal-transactions

#### `GET /api/v1/internal-transactions/`

**Operation:** `internal_transactions_list`

Return budget-to-budget transfers belonging to the authenticated user's accounts. Filterable by bank_account, src_budget, dst_budget, and date range (date_from/date_to). Orderable by created_at.

**Parameters:**

- `bank_account` (query, optional)
- `budget` (query, optional)
- `date_from` (query, optional)
- `date_to` (query, optional)
- `dst_budget` (query, optional)
- `ordering` (query, optional) — Which field to use when ordering the results.
- `page` (query, optional) — A page number within the paginated result set.
- `page_size` (query, optional) — Number of results to return per page.
- `src_budget` (query, optional)

**Response 200:** 

- **`count`** (`integer`) *(required)*
- **`next`** (`string`)
- **`previous`** (`string`)
- **`results`** (`array`) *(required)*

#### `POST /api/v1/internal-transactions/`

**Operation:** `internal_transactions_create`

Transfer money between two budgets in the same bank account. Required: bank_account (UUID), amount, src_budget (UUID), and dst_budget (UUID). The authenticated user is recorded as the actor. Internal transactions are write-once -- to reverse a transfer, create a new one with src and dst swapped.

**Request Body** (`application/json`):

- **`bank_account`** (`string`) *(required)*
- **`amount`** (`string`) *(required)*
- **`src_budget`** (`string`) *(required)*
- **`dst_budget`** (`string`) *(required)*
- **`effective_date`** (`string`)

**Request Body** (`application/x-www-form-urlencoded`):

- **`bank_account`** (`string`) *(required)*
- **`amount`** (`string`) *(required)*
- **`src_budget`** (`string`) *(required)*
- **`dst_budget`** (`string`) *(required)*
- **`effective_date`** (`string`)

**Request Body** (`multipart/form-data`):

- **`bank_account`** (`string`) *(required)*
- **`amount`** (`string`) *(required)*
- **`src_budget`** (`string`) *(required)*
- **`dst_budget`** (`string`) *(required)*
- **`effective_date`** (`string`)

**Response 201:** 

- **`id`** (`string`) *(required, read-only)*
- **`bank_account`** (`string`) *(required)*
- **`amount`** (`string`) *(required)*
- **`amount_currency`** (`string`) *(required, read-only)*
- **`src_budget`** (`string`) *(required)*
- **`dst_budget`** (`string`) *(required)*
- **`actor`** (`integer`) *(required, read-only)*
- **`effective_date`** (`string`)
- **`src_budget_balance`** (`string`) *(required, read-only)*
- **`src_budget_balance_currency`** (`string`) *(required, read-only)*
- **`dst_budget_balance`** (`string`) *(required, read-only)*
- **`dst_budget_balance_currency`** (`string`) *(required, read-only)*
- **`created_at`** (`string`) *(required, read-only)*
- **`modified_at`** (`string`) *(required, read-only)*

#### `GET /api/v1/internal-transactions/{id}/`

**Operation:** `internal_transactions_retrieve`

Return a single internal transaction by UUID.

**Parameters:**

- `id` (path, required)

**Response 200:** 

- **`id`** (`string`) *(required, read-only)*
- **`bank_account`** (`string`) *(required)*
- **`amount`** (`string`) *(required)*
- **`amount_currency`** (`string`) *(required, read-only)*
- **`src_budget`** (`string`) *(required)*
- **`dst_budget`** (`string`) *(required)*
- **`actor`** (`integer`) *(required, read-only)*
- **`effective_date`** (`string`)
- **`src_budget_balance`** (`string`) *(required, read-only)*
- **`src_budget_balance_currency`** (`string`) *(required, read-only)*
- **`dst_budget_balance`** (`string`) *(required, read-only)*
- **`dst_budget_balance_currency`** (`string`) *(required, read-only)*
- **`created_at`** (`string`) *(required, read-only)*
- **`modified_at`** (`string`) *(required, read-only)*

### invitations

#### `GET /api/v1/invitations/{token}/`

**Operation:** `invitations_retrieve`

Return bank account name, current owners, and invitee status for the invitation identified by *token*. No authentication required -- the token is the credential. Used by native apps to render the acceptance UI; the Django template view renders this server-side.

**Parameters:**

- `token` (path, required)

**Response 200:** 

- **`id`** (`string`) *(required, read-only)*
- **`status`** (``) *(required, read-only)*
- **`invitee_email`** (`string`) *(required, read-only)* — Email address the invitation was sent to. Immutable after creation.
- **`bank_account_name`** (`string`) *(required, read-only)*
- **`bank_name`** (`string`) *(required, read-only)*
- **`current_owners`** (`array`) *(required, read-only)*
- **`is_new_user`** (`boolean`) *(required, read-only)*
- **`expires_at`** (`string`) *(required, read-only)*

#### `POST /api/v1/invitations/{token}/accept/`

**Operation:** `invitations_accept_create`

Accept the co-ownership invitation identified by *token*. Adds the invitee to the account's owners. For brand-new users (no password set), a password-reset email is also dispatched. No authentication required.

**Parameters:**

- `token` (path, required)

**Response 200:** No response body

**Response 400:** Invitation expired, cancelled, or already resolved.

**Response 404:** Invitation not found.

#### `POST /api/v1/invitations/{token}/decline/`

**Operation:** `invitations_decline_create`

Decline the co-ownership invitation identified by *token*. No authentication required.

**Parameters:**

- `token` (path, required)

**Response 200:** No response body

**Response 400:** Invitation expired, cancelled, or already resolved.

**Response 404:** Invitation not found.

### notification-preferences

#### `GET /api/v1/notification-preferences/`

**Operation:** `notification_preferences_list`

Return all registered notification kinds merged with the authenticated user's preferences. Kinds without a stored preference fall back to the registry default_delivery_mode.

**Parameters:**

- `page` (query, optional) — A page number within the paginated result set.
- `page_size` (query, optional) — Number of results to return per page.

**Response 200:** 

- **`count`** (`integer`) *(required)*
- **`next`** (`string`)
- **`previous`** (`string`)
- **`results`** (`array`) *(required)*

#### `PATCH /api/v1/notification-preferences/{kind}/`

**Operation:** `notification_preferences_partial_update`

Set delivery_mode ('digest', 'immediate', or 'off') for a single notification kind. Returns 400 if the kind has can_suppress=False. Returns 404 if the kind is not registered.

**Parameters:**

- `kind` (path, required)

**Request Body** (`application/json`):

- **`delivery_mode`** (`string`) — * `digest` - Digest
* `immediate` - Immediate
* `off` - Off Enum: ['digest', 'immediate', 'off']

**Request Body** (`application/x-www-form-urlencoded`):

- **`delivery_mode`** (`string`) — * `digest` - Digest
* `immediate` - Immediate
* `off` - Off Enum: ['digest', 'immediate', 'off']

**Request Body** (`multipart/form-data`):

- **`delivery_mode`** (`string`) — * `digest` - Digest
* `immediate` - Immediate
* `off` - Off Enum: ['digest', 'immediate', 'off']

**Response 200:** 

- **`kind`** (`string`) *(required, read-only)*
- **`display_name`** (`string`) *(required, read-only)*
- **`can_suppress`** (`boolean`) *(required, read-only)*
- **`delivery_mode`** (`string`) *(required)* — * `digest` - Digest
* `immediate` - Immediate
* `off` - Off Enum: ['digest', 'immediate', 'off']

### transaction-categories

#### `GET /api/v1/transaction-categories/`

**Operation:** `transaction_categories_list`

Return the transaction categories visible to the authenticated user: the global base set, the user's own custom categories, categories owned by users they co-own a bank account with, and categories still referenced by the user's transactions after sharing ended.  Filterable by group, archived, and scope (global|mine|shared).  Searchable by group and name.

**Parameters:**

- `archived` (query, optional)
- `group` (query, optional)
- `ordering` (query, optional) — Which field to use when ordering the results.
- `page` (query, optional) — A page number within the paginated result set.
- `page_size` (query, optional) — Number of results to return per page.
- `scope` (query, optional) — * `global` - Global
* `mine` - Mine
* `shared` - Shared
- `search` (query, optional) — A search term.

**Response 200:** 

- **`count`** (`integer`) *(required)*
- **`next`** (`string`)
- **`previous`** (`string`)
- **`results`** (`array`) *(required)*

#### `POST /api/v1/transaction-categories/`

**Operation:** `transaction_categories_create`

Create a custom category owned by the authenticated user (global categories are managed via the admin).  Group and name are whitespace-normalized; case-insensitive duplicates of global rows or the user's own rows are rejected.

**Request Body** (`application/json`):

- **`group`** (`string`) *(required)*
- **`name`** (`string`) *(required)*

**Request Body** (`application/x-www-form-urlencoded`):

- **`group`** (`string`) *(required)*
- **`name`** (`string`) *(required)*

**Request Body** (`multipart/form-data`):

- **`group`** (`string`) *(required)*
- **`name`** (`string`) *(required)*

**Response 201:** 

- **`id`** (`string`) *(required, read-only)*
- **`group`** (`string`) *(required)*
- **`name`** (`string`) *(required)*
- **`full_name`** (`string`) *(required, read-only)* — Canonical display form: '{group} : {name}'.
- **`owner`** (`string`) *(required, read-only)* — Owner username; null for a global category.
- **`archived`** (`boolean`) *(required, read-only)* — Archived categories are hidden from pickers but remain valid on existing transactions and allocations.
- **`created_at`** (`string`) *(required, read-only)*
- **`modified_at`** (`string`) *(required, read-only)*

#### `GET /api/v1/transaction-categories/{id}/`

**Operation:** `transaction_categories_retrieve`

Return a single visible category by UUID.

**Parameters:**

- `id` (path, required)

**Response 200:** 

- **`id`** (`string`) *(required, read-only)*
- **`group`** (`string`) *(required)*
- **`name`** (`string`) *(required)*
- **`full_name`** (`string`) *(required, read-only)* — Canonical display form: '{group} : {name}'.
- **`owner`** (`string`) *(required, read-only)* — Owner username; null for a global category.
- **`archived`** (`boolean`) *(required, read-only)* — Archived categories are hidden from pickers but remain valid on existing transactions and allocations.
- **`created_at`** (`string`) *(required, read-only)*
- **`modified_at`** (`string`) *(required, read-only)*

#### `PUT /api/v1/transaction-categories/{id}/`

**Operation:** `transaction_categories_update`

Full update of a category.  Only the owner may update; global categories are managed via the admin.

**Parameters:**

- `id` (path, required)

**Request Body** (`application/json`):

- **`group`** (`string`) *(required)*
- **`name`** (`string`) *(required)*

**Request Body** (`application/x-www-form-urlencoded`):

- **`group`** (`string`) *(required)*
- **`name`** (`string`) *(required)*

**Request Body** (`multipart/form-data`):

- **`group`** (`string`) *(required)*
- **`name`** (`string`) *(required)*

**Response 200:** 

- **`id`** (`string`) *(required, read-only)*
- **`group`** (`string`) *(required)*
- **`name`** (`string`) *(required)*
- **`full_name`** (`string`) *(required, read-only)* — Canonical display form: '{group} : {name}'.
- **`owner`** (`string`) *(required, read-only)* — Owner username; null for a global category.
- **`archived`** (`boolean`) *(required, read-only)* — Archived categories are hidden from pickers but remain valid on existing transactions and allocations.
- **`created_at`** (`string`) *(required, read-only)*
- **`modified_at`** (`string`) *(required, read-only)*

#### `PATCH /api/v1/transaction-categories/{id}/`

**Operation:** `transaction_categories_partial_update`

Partial update of a category.  Only the owner may update; global categories are managed via the admin.

**Parameters:**

- `id` (path, required)

**Request Body** (`application/json`):

- **`group`** (`string`)
- **`name`** (`string`)

**Request Body** (`application/x-www-form-urlencoded`):

- **`group`** (`string`)
- **`name`** (`string`)

**Request Body** (`multipart/form-data`):

- **`group`** (`string`)
- **`name`** (`string`)

**Response 200:** 

- **`id`** (`string`) *(required, read-only)*
- **`group`** (`string`) *(required)*
- **`name`** (`string`) *(required)*
- **`full_name`** (`string`) *(required, read-only)* — Canonical display form: '{group} : {name}'.
- **`owner`** (`string`) *(required, read-only)* — Owner username; null for a global category.
- **`archived`** (`boolean`) *(required, read-only)* — Archived categories are hidden from pickers but remain valid on existing transactions and allocations.
- **`created_at`** (`string`) *(required, read-only)*
- **`modified_at`** (`string`) *(required, read-only)*

#### `DELETE /api/v1/transaction-categories/{id}/`

**Operation:** `transaction_categories_destroy`

Delete a category.  Only the owner may delete; global categories are managed via the admin.  A category still referenced by transactions or allocations cannot be deleted (409) -- archive it instead.

**Parameters:**

- `id` (path, required)

**Response 204:** No response body

**Response 409:** The category is referenced by transactions or allocations; archive it instead.

#### `POST /api/v1/transaction-categories/{id}/archive/`

**Operation:** `transaction_categories_archive_create`

Archive a category so pickers hide it while existing references stay valid.  Only the owner may archive; global categories are managed via the admin.

**Parameters:**

- `id` (path, required)

**Response 200:** 

- **`id`** (`string`) *(required, read-only)*
- **`group`** (`string`) *(required)*
- **`name`** (`string`) *(required)*
- **`full_name`** (`string`) *(required, read-only)* — Canonical display form: '{group} : {name}'.
- **`owner`** (`string`) *(required, read-only)* — Owner username; null for a global category.
- **`archived`** (`boolean`) *(required, read-only)* — Archived categories are hidden from pickers but remain valid on existing transactions and allocations.
- **`created_at`** (`string`) *(required, read-only)*
- **`modified_at`** (`string`) *(required, read-only)*

### transactions

#### `GET /api/v1/transactions/`

**Operation:** `transactions_list`

Return transactions belonging to the authenticated user's accounts. Filterable by bank_account, pending status, transaction_type, and date range (date_from/date_to). Searchable by description, raw_description, and party. Orderable by transaction_date, amount, or created_at.

**Parameters:**

- `bank_account` (query, optional)
- `category` (query, optional)
- `category_group` (query, optional)
- `date_from` (query, optional)
- `date_to` (query, optional)
- `has_details` (query, optional)
- `merchant_category_code` (query, optional)
- `merchant_city` (query, optional)
- `merchant_name` (query, optional)
- `merchant_region` (query, optional)
- `ordering` (query, optional) — Which field to use when ordering the results.
- `page` (query, optional) — A page number within the paginated result set.
- `page_size` (query, optional) — Number of results to return per page.
- `pending` (query, optional)
- `posted_date_from` (query, optional)
- `posted_date_to` (query, optional)
- `search` (query, optional) — A search term.
- `transaction_type` (query, optional) — * `signature_purchase` - Signature Purchase
* `ach` - ACH
* `round-up_transfer` - Round-up Transfer
* `protected_goal_account_transfer` - Protected Goal Account Transfer
* `fee` - Fee
* `pin_purchase` - Pin Purchase
* `signature_credit` - Signature Credit
* `interest_credit` - Interest Credit
* `shared_transfer` - Shared Transfer
* `courtesy_credit` - Courtesy Credit
* `atm_withdrawal` - ATM Withdrawal
* `bill_payment` - Bill Payment
* `bank_generated_credit` - Bank Generated Credit
* `wire_transfer` - Wire Transfer
* `check_deposit` - Check Deposit
* `check` - Check
* `c2c` - c2c
* `migration_interbank_transfer` - Migration Interbank Transfer
* `balance_sweep` - Balance Sweep
* `ach_reversal` - ACH Reversal
* `adjustment` - Adjustment
* `signature_return` - Signature return
* `fx_order` - FX Order
* `` - --------
- `uncategorized` (query, optional)
- `virtual_card_last4` (query, optional)

**Response 200:** 

- **`count`** (`integer`) *(required)*
- **`next`** (`string`)
- **`previous`** (`string`)
- **`results`** (`array`) *(required)*

#### `POST /api/v1/transactions/`

**Operation:** `transactions_create`

Create a new bank transaction. Required: bank_account (UUID), amount, transaction_date, transaction_type, and raw_description. A default TransactionAllocation to the bank account's unallocated budget is auto-created. After creation, only transaction_type, memo, and description are updatable.

**Request Body** (`application/json`):

- **`bank_account`** (`string`) *(required)*
- **`amount`** (`string`) *(required)*
- **`posted_date`** (`string`) *(required)*
- **`transaction_date`** (`string`)
- **`transaction_type`** (``) *(required)*
- **`pending`** (`boolean`)
- **`memo`** (`string`)
- **`raw_description`** (`string`) *(required)*
- **`description`** (`string`)
- **`category`** (`string`)
- **`merchant_address`** (`string`)
- **`merchant_city`** (`string`)
- **`merchant_region`** (`string`)
- **`merchant_country`** (`string`)
- **`merchant_latitude`** (`string`)
- **`merchant_longitude`** (`string`)
- **`bank_transaction_id`** (`string`)
- **`image`** (`string`)
- **`document`** (`string`)

**Request Body** (`application/x-www-form-urlencoded`):

- **`bank_account`** (`string`) *(required)*
- **`amount`** (`string`) *(required)*
- **`posted_date`** (`string`) *(required)*
- **`transaction_date`** (`string`)
- **`transaction_type`** (``) *(required)*
- **`pending`** (`boolean`)
- **`memo`** (`string`)
- **`raw_description`** (`string`) *(required)*
- **`description`** (`string`)
- **`category`** (`string`)
- **`merchant_address`** (`string`)
- **`merchant_city`** (`string`)
- **`merchant_region`** (`string`)
- **`merchant_country`** (`string`)
- **`merchant_latitude`** (`string`)
- **`merchant_longitude`** (`string`)
- **`bank_transaction_id`** (`string`)
- **`image`** (`string`)
- **`document`** (`string`)

**Request Body** (`multipart/form-data`):

- **`bank_account`** (`string`) *(required)*
- **`amount`** (`string`) *(required)*
- **`posted_date`** (`string`) *(required)*
- **`transaction_date`** (`string`)
- **`transaction_type`** (``) *(required)*
- **`pending`** (`boolean`)
- **`memo`** (`string`)
- **`raw_description`** (`string`) *(required)*
- **`description`** (`string`)
- **`category`** (`string`)
- **`merchant_address`** (`string`)
- **`merchant_city`** (`string`)
- **`merchant_region`** (`string`)
- **`merchant_country`** (`string`)
- **`merchant_latitude`** (`string`)
- **`merchant_longitude`** (`string`)
- **`bank_transaction_id`** (`string`)
- **`image`** (`string`)
- **`document`** (`string`)

**Response 201:** 

- **`id`** (`string`) *(required, read-only)*
- **`bank_account`** (`string`) *(required)*
- **`amount`** (`string`) *(required)*
- **`amount_currency`** (`string`) *(required, read-only)*
- **`party`** (`string`) *(required, read-only)*
- **`posted_date`** (`string`) *(required)*
- **`transaction_date`** (`string`)
- **`transaction_type`** (``) *(required)*
- **`pending`** (`boolean`)
- **`memo`** (`string`)
- **`raw_description`** (`string`) *(required)*
- **`description`** (`string`)
- **`description_user_edited`** (`boolean`) *(required, read-only)*
- **`category`** (`string`)
- **`category_full_name`** (`string`) *(required, read-only)*
- **`merchant_name`** (`string`) *(required, read-only)*
- **`merchant_address`** (`string`)
- **`merchant_city`** (`string`)
- **`merchant_region`** (`string`)
- **`merchant_country`** (`string`)
- **`merchant_latitude`** (`string`)
- **`merchant_longitude`** (`string`)
- **`merchant_category`** (`string`) *(required, read-only)*
- **`merchant_category_code`** (`string`) *(required, read-only)*
- **`virtual_card_number`** (`string`) *(required, read-only)*
- **`has_details`** (`boolean`) *(required, read-only)*
- **`bank_transaction_id`** (`string`)
- **`linked_transaction`** (`string`) *(required, read-only)*
- **`bank_account_posted_balance`** (`string`) *(required, read-only)* — Posted Balance does not include pending debits.
- **`bank_account_posted_balance_currency`** (`string`) *(required, read-only)*
- **`bank_account_available_balance`** (`string`) *(required, read-only)* — Available Balance has pending debits deducted.
- **`bank_account_available_balance_currency`** (`string`) *(required, read-only)*
- **`image`** (`string`)
- **`document`** (`string`)
- **`created_at`** (`string`) *(required, read-only)*
- **`modified_at`** (`string`) *(required, read-only)*

#### `GET /api/v1/transactions/{id}/`

**Operation:** `transactions_retrieve`

Return a single transaction by UUID.

**Parameters:**

- `id` (path, required)

**Response 200:** 

- **`id`** (`string`) *(required, read-only)*
- **`bank_account`** (`string`) *(required)*
- **`amount`** (`string`) *(required)*
- **`amount_currency`** (`string`) *(required, read-only)*
- **`party`** (`string`) *(required, read-only)*
- **`posted_date`** (`string`) *(required)*
- **`transaction_date`** (`string`)
- **`transaction_type`** (``) *(required)*
- **`pending`** (`boolean`)
- **`memo`** (`string`)
- **`raw_description`** (`string`) *(required)*
- **`description`** (`string`)
- **`description_user_edited`** (`boolean`) *(required, read-only)*
- **`category`** (`string`)
- **`category_full_name`** (`string`) *(required, read-only)*
- **`merchant_name`** (`string`) *(required, read-only)*
- **`merchant_address`** (`string`)
- **`merchant_city`** (`string`)
- **`merchant_region`** (`string`)
- **`merchant_country`** (`string`)
- **`merchant_latitude`** (`string`)
- **`merchant_longitude`** (`string`)
- **`merchant_category`** (`string`) *(required, read-only)*
- **`merchant_category_code`** (`string`) *(required, read-only)*
- **`virtual_card_number`** (`string`) *(required, read-only)*
- **`has_details`** (`boolean`) *(required, read-only)*
- **`bank_transaction_id`** (`string`)
- **`linked_transaction`** (`string`) *(required, read-only)*
- **`bank_account_posted_balance`** (`string`) *(required, read-only)* — Posted Balance does not include pending debits.
- **`bank_account_posted_balance_currency`** (`string`) *(required, read-only)*
- **`bank_account_available_balance`** (`string`) *(required, read-only)* — Available Balance has pending debits deducted.
- **`bank_account_available_balance_currency`** (`string`) *(required, read-only)*
- **`image`** (`string`)
- **`document`** (`string`)
- **`created_at`** (`string`) *(required, read-only)*
- **`modified_at`** (`string`) *(required, read-only)*

#### `PUT /api/v1/transactions/{id}/`

**Operation:** `transactions_update`

Full update of a transaction. Only transaction_type, memo, and description are mutable after creation.

**Parameters:**

- `id` (path, required)

**Request Body** (`application/json`):

- **`bank_account`** (`string`) *(required)*
- **`amount`** (`string`) *(required)*
- **`posted_date`** (`string`) *(required)*
- **`transaction_date`** (`string`)
- **`transaction_type`** (``) *(required)*
- **`pending`** (`boolean`)
- **`memo`** (`string`)
- **`raw_description`** (`string`) *(required)*
- **`description`** (`string`)
- **`category`** (`string`)
- **`merchant_address`** (`string`)
- **`merchant_city`** (`string`)
- **`merchant_region`** (`string`)
- **`merchant_country`** (`string`)
- **`merchant_latitude`** (`string`)
- **`merchant_longitude`** (`string`)
- **`bank_transaction_id`** (`string`)
- **`image`** (`string`)
- **`document`** (`string`)

**Request Body** (`application/x-www-form-urlencoded`):

- **`bank_account`** (`string`) *(required)*
- **`amount`** (`string`) *(required)*
- **`posted_date`** (`string`) *(required)*
- **`transaction_date`** (`string`)
- **`transaction_type`** (``) *(required)*
- **`pending`** (`boolean`)
- **`memo`** (`string`)
- **`raw_description`** (`string`) *(required)*
- **`description`** (`string`)
- **`category`** (`string`)
- **`merchant_address`** (`string`)
- **`merchant_city`** (`string`)
- **`merchant_region`** (`string`)
- **`merchant_country`** (`string`)
- **`merchant_latitude`** (`string`)
- **`merchant_longitude`** (`string`)
- **`bank_transaction_id`** (`string`)
- **`image`** (`string`)
- **`document`** (`string`)

**Request Body** (`multipart/form-data`):

- **`bank_account`** (`string`) *(required)*
- **`amount`** (`string`) *(required)*
- **`posted_date`** (`string`) *(required)*
- **`transaction_date`** (`string`)
- **`transaction_type`** (``) *(required)*
- **`pending`** (`boolean`)
- **`memo`** (`string`)
- **`raw_description`** (`string`) *(required)*
- **`description`** (`string`)
- **`category`** (`string`)
- **`merchant_address`** (`string`)
- **`merchant_city`** (`string`)
- **`merchant_region`** (`string`)
- **`merchant_country`** (`string`)
- **`merchant_latitude`** (`string`)
- **`merchant_longitude`** (`string`)
- **`bank_transaction_id`** (`string`)
- **`image`** (`string`)
- **`document`** (`string`)

**Response 200:** 

- **`id`** (`string`) *(required, read-only)*
- **`bank_account`** (`string`) *(required)*
- **`amount`** (`string`) *(required)*
- **`amount_currency`** (`string`) *(required, read-only)*
- **`party`** (`string`) *(required, read-only)*
- **`posted_date`** (`string`) *(required)*
- **`transaction_date`** (`string`)
- **`transaction_type`** (``) *(required)*
- **`pending`** (`boolean`)
- **`memo`** (`string`)
- **`raw_description`** (`string`) *(required)*
- **`description`** (`string`)
- **`description_user_edited`** (`boolean`) *(required, read-only)*
- **`category`** (`string`)
- **`category_full_name`** (`string`) *(required, read-only)*
- **`merchant_name`** (`string`) *(required, read-only)*
- **`merchant_address`** (`string`)
- **`merchant_city`** (`string`)
- **`merchant_region`** (`string`)
- **`merchant_country`** (`string`)
- **`merchant_latitude`** (`string`)
- **`merchant_longitude`** (`string`)
- **`merchant_category`** (`string`) *(required, read-only)*
- **`merchant_category_code`** (`string`) *(required, read-only)*
- **`virtual_card_number`** (`string`) *(required, read-only)*
- **`has_details`** (`boolean`) *(required, read-only)*
- **`bank_transaction_id`** (`string`)
- **`linked_transaction`** (`string`) *(required, read-only)*
- **`bank_account_posted_balance`** (`string`) *(required, read-only)* — Posted Balance does not include pending debits.
- **`bank_account_posted_balance_currency`** (`string`) *(required, read-only)*
- **`bank_account_available_balance`** (`string`) *(required, read-only)* — Available Balance has pending debits deducted.
- **`bank_account_available_balance_currency`** (`string`) *(required, read-only)*
- **`image`** (`string`)
- **`document`** (`string`)
- **`created_at`** (`string`) *(required, read-only)*
- **`modified_at`** (`string`) *(required, read-only)*

#### `PATCH /api/v1/transactions/{id}/`

**Operation:** `transactions_partial_update`

Partial update of a transaction. Only transaction_type, memo, and description are mutable after creation.

**Parameters:**

- `id` (path, required)

**Request Body** (`application/json`):

- **`bank_account`** (`string`)
- **`amount`** (`string`)
- **`posted_date`** (`string`)
- **`transaction_date`** (`string`)
- **`transaction_type`** (``)
- **`pending`** (`boolean`)
- **`memo`** (`string`)
- **`raw_description`** (`string`)
- **`description`** (`string`)
- **`category`** (`string`)
- **`merchant_address`** (`string`)
- **`merchant_city`** (`string`)
- **`merchant_region`** (`string`)
- **`merchant_country`** (`string`)
- **`merchant_latitude`** (`string`)
- **`merchant_longitude`** (`string`)
- **`bank_transaction_id`** (`string`)
- **`image`** (`string`)
- **`document`** (`string`)

**Request Body** (`application/x-www-form-urlencoded`):

- **`bank_account`** (`string`)
- **`amount`** (`string`)
- **`posted_date`** (`string`)
- **`transaction_date`** (`string`)
- **`transaction_type`** (``)
- **`pending`** (`boolean`)
- **`memo`** (`string`)
- **`raw_description`** (`string`)
- **`description`** (`string`)
- **`category`** (`string`)
- **`merchant_address`** (`string`)
- **`merchant_city`** (`string`)
- **`merchant_region`** (`string`)
- **`merchant_country`** (`string`)
- **`merchant_latitude`** (`string`)
- **`merchant_longitude`** (`string`)
- **`bank_transaction_id`** (`string`)
- **`image`** (`string`)
- **`document`** (`string`)

**Request Body** (`multipart/form-data`):

- **`bank_account`** (`string`)
- **`amount`** (`string`)
- **`posted_date`** (`string`)
- **`transaction_date`** (`string`)
- **`transaction_type`** (``)
- **`pending`** (`boolean`)
- **`memo`** (`string`)
- **`raw_description`** (`string`)
- **`description`** (`string`)
- **`category`** (`string`)
- **`merchant_address`** (`string`)
- **`merchant_city`** (`string`)
- **`merchant_region`** (`string`)
- **`merchant_country`** (`string`)
- **`merchant_latitude`** (`string`)
- **`merchant_longitude`** (`string`)
- **`bank_transaction_id`** (`string`)
- **`image`** (`string`)
- **`document`** (`string`)

**Response 200:** 

- **`id`** (`string`) *(required, read-only)*
- **`bank_account`** (`string`) *(required)*
- **`amount`** (`string`) *(required)*
- **`amount_currency`** (`string`) *(required, read-only)*
- **`party`** (`string`) *(required, read-only)*
- **`posted_date`** (`string`) *(required)*
- **`transaction_date`** (`string`)
- **`transaction_type`** (``) *(required)*
- **`pending`** (`boolean`)
- **`memo`** (`string`)
- **`raw_description`** (`string`) *(required)*
- **`description`** (`string`)
- **`description_user_edited`** (`boolean`) *(required, read-only)*
- **`category`** (`string`)
- **`category_full_name`** (`string`) *(required, read-only)*
- **`merchant_name`** (`string`) *(required, read-only)*
- **`merchant_address`** (`string`)
- **`merchant_city`** (`string`)
- **`merchant_region`** (`string`)
- **`merchant_country`** (`string`)
- **`merchant_latitude`** (`string`)
- **`merchant_longitude`** (`string`)
- **`merchant_category`** (`string`) *(required, read-only)*
- **`merchant_category_code`** (`string`) *(required, read-only)*
- **`virtual_card_number`** (`string`) *(required, read-only)*
- **`has_details`** (`boolean`) *(required, read-only)*
- **`bank_transaction_id`** (`string`)
- **`linked_transaction`** (`string`) *(required, read-only)*
- **`bank_account_posted_balance`** (`string`) *(required, read-only)* — Posted Balance does not include pending debits.
- **`bank_account_posted_balance_currency`** (`string`) *(required, read-only)*
- **`bank_account_available_balance`** (`string`) *(required, read-only)* — Available Balance has pending debits deducted.
- **`bank_account_available_balance_currency`** (`string`) *(required, read-only)*
- **`image`** (`string`)
- **`document`** (`string`)
- **`created_at`** (`string`) *(required, read-only)*
- **`modified_at`** (`string`) *(required, read-only)*

#### `DELETE /api/v1/transactions/{id}/`

**Operation:** `transactions_destroy`

Delete a transaction. Balance changes are reversed by the pre_delete signal. Associated allocations are cascade-deleted.

**Parameters:**

- `id` (path, required)

**Response 204:** No response body

#### `POST /api/v1/transactions/{id}/resolve-pending/`

**Operation:** `transactions_resolve_pending_create`

Transition a pending transaction to posted status. Supplies the bank-confirmed posted date and optionally a final settled amount (which may differ from the pending estimate). The bank account's posted_balance is credited; if the amount changed, available_balance and the Unallocated allocation are adjusted atomically.

**Parameters:**

- `id` (path, required)

**Request Body** (`application/json`):

- **`posted_date`** (`string`) *(required)*
- **`amount`** (`string`)

**Request Body** (`application/x-www-form-urlencoded`):

- **`posted_date`** (`string`) *(required)*
- **`amount`** (`string`)

**Request Body** (`multipart/form-data`):

- **`posted_date`** (`string`) *(required)*
- **`amount`** (`string`)

**Response 200:** 

- **`id`** (`string`) *(required, read-only)*
- **`bank_account`** (`string`) *(required)*
- **`amount`** (`string`) *(required)*
- **`amount_currency`** (`string`) *(required, read-only)*
- **`party`** (`string`) *(required, read-only)*
- **`posted_date`** (`string`) *(required)*
- **`transaction_date`** (`string`)
- **`transaction_type`** (``) *(required)*
- **`pending`** (`boolean`)
- **`memo`** (`string`)
- **`raw_description`** (`string`) *(required)*
- **`description`** (`string`)
- **`description_user_edited`** (`boolean`) *(required, read-only)*
- **`category`** (`string`)
- **`category_full_name`** (`string`) *(required, read-only)*
- **`merchant_name`** (`string`) *(required, read-only)*
- **`merchant_address`** (`string`)
- **`merchant_city`** (`string`)
- **`merchant_region`** (`string`)
- **`merchant_country`** (`string`)
- **`merchant_latitude`** (`string`)
- **`merchant_longitude`** (`string`)
- **`merchant_category`** (`string`) *(required, read-only)*
- **`merchant_category_code`** (`string`) *(required, read-only)*
- **`virtual_card_number`** (`string`) *(required, read-only)*
- **`has_details`** (`boolean`) *(required, read-only)*
- **`bank_transaction_id`** (`string`)
- **`linked_transaction`** (`string`) *(required, read-only)*
- **`bank_account_posted_balance`** (`string`) *(required, read-only)* — Posted Balance does not include pending debits.
- **`bank_account_posted_balance_currency`** (`string`) *(required, read-only)*
- **`bank_account_available_balance`** (`string`) *(required, read-only)* — Available Balance has pending debits deducted.
- **`bank_account_available_balance_currency`** (`string`) *(required, read-only)*
- **`image`** (`string`)
- **`document`** (`string`)
- **`created_at`** (`string`) *(required, read-only)*
- **`modified_at`** (`string`) *(required, read-only)*

#### `POST /api/v1/transactions/{id}/splits/`

**Operation:** `transactions_splits_create`

Declaratively set how a transaction's amount is split across budgets. All referenced budgets must belong to the same bank account as the transaction. The backend reconciles existing allocations to match: creating, updating, or deleting as needed. Any unallocated remainder gets an allocation to the account's unallocated budget. Returns all allocations for this transaction after reconciliation.

**Parameters:**

- `bank_account` (query, optional)
- `category` (query, optional)
- `category_group` (query, optional)
- `date_from` (query, optional)
- `date_to` (query, optional)
- `has_details` (query, optional)
- `id` (path, required)
- `merchant_category_code` (query, optional)
- `merchant_city` (query, optional)
- `merchant_name` (query, optional)
- `merchant_region` (query, optional)
- `ordering` (query, optional) — Which field to use when ordering the results.
- `page` (query, optional) — A page number within the paginated result set.
- `page_size` (query, optional) — Number of results to return per page.
- `pending` (query, optional)
- `posted_date_from` (query, optional)
- `posted_date_to` (query, optional)
- `search` (query, optional) — A search term.
- `transaction_type` (query, optional) — * `signature_purchase` - Signature Purchase
* `ach` - ACH
* `round-up_transfer` - Round-up Transfer
* `protected_goal_account_transfer` - Protected Goal Account Transfer
* `fee` - Fee
* `pin_purchase` - Pin Purchase
* `signature_credit` - Signature Credit
* `interest_credit` - Interest Credit
* `shared_transfer` - Shared Transfer
* `courtesy_credit` - Courtesy Credit
* `atm_withdrawal` - ATM Withdrawal
* `bill_payment` - Bill Payment
* `bank_generated_credit` - Bank Generated Credit
* `wire_transfer` - Wire Transfer
* `check_deposit` - Check Deposit
* `check` - Check
* `c2c` - c2c
* `migration_interbank_transfer` - Migration Interbank Transfer
* `balance_sweep` - Balance Sweep
* `ach_reversal` - ACH Reversal
* `adjustment` - Adjustment
* `signature_return` - Signature return
* `fx_order` - FX Order
* `` - --------
- `uncategorized` (query, optional)
- `virtual_card_last4` (query, optional)

**Request Body** (`application/json`):

- **`splits`** (`object`) *(required)* — Map of budget UUID → amount.  Amounts must not exceed the transaction total.  Omitted remainder is assigned to the unallocated budget.

**Request Body** (`application/x-www-form-urlencoded`):

- **`splits`** (`object`) *(required)* — Map of budget UUID → amount.  Amounts must not exceed the transaction total.  Omitted remainder is assigned to the unallocated budget.

**Request Body** (`multipart/form-data`):

- **`splits`** (`object`) *(required)* — Map of budget UUID → amount.  Amounts must not exceed the transaction total.  Omitted remainder is assigned to the unallocated budget.

**Response 200:** 

- **`count`** (`integer`) *(required)*
- **`next`** (`string`)
- **`previous`** (`string`)
- **`results`** (`array`) *(required)*

### users

#### `GET /api/v1/users/`

**Operation:** `users_list`

Return all users. Restricted to staff/admin users.

**Parameters:**

- `ordering` (query, optional) — Which field to use when ordering the results.
- `page` (query, optional) — A page number within the paginated result set.
- `page_size` (query, optional) — Number of results to return per page.

**Response 200:** 

- **`count`** (`integer`) *(required)*
- **`next`** (`string`)
- **`previous`** (`string`)
- **`results`** (`array`) *(required)*

#### `GET /api/v1/users/{username}/`

**Operation:** `users_retrieve`

Return a single user by username. Restricted to staff/admin users.

**Parameters:**

- `username` (path, required)

**Response 200:** 

- **`username`** (`string`) *(required, read-only)* — Required. 150 characters or fewer. Letters, digits and @/./+/-/_ only.
- **`email`** (`string`) *(required, read-only)*
- **`name`** (`string`)
- **`url`** (`string`) *(required, read-only)*
- **`default_bank_account`** (`string`)
- **`timezone`** (`string`)
- **`has_usable_password`** (`boolean`) *(required, read-only)* — Return True if the user has a usable (non-unusable) password set.

#### `PUT /api/v1/users/{username}/`

**Operation:** `users_update`

Full update of a user profile. Restricted to staff/admin users.

**Parameters:**

- `username` (path, required)

**Request Body** (`application/json`):

- **`name`** (`string`)
- **`default_bank_account`** (`string`)
- **`timezone`** (`string`)

**Request Body** (`application/x-www-form-urlencoded`):

- **`name`** (`string`)
- **`default_bank_account`** (`string`)
- **`timezone`** (`string`)

**Request Body** (`multipart/form-data`):

- **`name`** (`string`)
- **`default_bank_account`** (`string`)
- **`timezone`** (`string`)

**Response 200:** 

- **`username`** (`string`) *(required, read-only)* — Required. 150 characters or fewer. Letters, digits and @/./+/-/_ only.
- **`email`** (`string`) *(required, read-only)*
- **`name`** (`string`)
- **`url`** (`string`) *(required, read-only)*
- **`default_bank_account`** (`string`)
- **`timezone`** (`string`)
- **`has_usable_password`** (`boolean`) *(required, read-only)* — Return True if the user has a usable (non-unusable) password set.

#### `PATCH /api/v1/users/{username}/`

**Operation:** `users_partial_update`

Partial update of a user profile. Restricted to staff/admin users.

**Parameters:**

- `username` (path, required)

**Request Body** (`application/json`):

- **`name`** (`string`)
- **`default_bank_account`** (`string`)
- **`timezone`** (`string`)

**Request Body** (`application/x-www-form-urlencoded`):

- **`name`** (`string`)
- **`default_bank_account`** (`string`)
- **`timezone`** (`string`)

**Request Body** (`multipart/form-data`):

- **`name`** (`string`)
- **`default_bank_account`** (`string`)
- **`timezone`** (`string`)

**Response 200:** 

- **`username`** (`string`) *(required, read-only)* — Required. 150 characters or fewer. Letters, digits and @/./+/-/_ only.
- **`email`** (`string`) *(required, read-only)*
- **`name`** (`string`)
- **`url`** (`string`) *(required, read-only)*
- **`default_bank_account`** (`string`)
- **`timezone`** (`string`)
- **`has_usable_password`** (`boolean`) *(required, read-only)* — Return True if the user has a usable (non-unusable) password set.

#### `GET /api/v1/users/me/`

**Operation:** `users_me_retrieve`

GET returns the authenticated user's own profile. PATCH allows updating the name field. Available to any authenticated user (not restricted to staff). GET is also available to machine credentials (API keys) -- importers read the timezone field; PATCH requires an interactive login session.

**Response 200:** 

- **`username`** (`string`) *(required, read-only)* — Required. 150 characters or fewer. Letters, digits and @/./+/-/_ only.
- **`email`** (`string`) *(required, read-only)*
- **`name`** (`string`)
- **`url`** (`string`) *(required, read-only)*
- **`default_bank_account`** (`string`)
- **`timezone`** (`string`)
- **`has_usable_password`** (`boolean`) *(required, read-only)* — Return True if the user has a usable (non-unusable) password set.

#### `PATCH /api/v1/users/me/`

**Operation:** `users_me_partial_update`

GET returns the authenticated user's own profile. PATCH allows updating the name field. Available to any authenticated user (not restricted to staff). GET is also available to machine credentials (API keys) -- importers read the timezone field; PATCH requires an interactive login session.

**Request Body** (`application/json`):

- **`name`** (`string`)
- **`default_bank_account`** (`string`)
- **`timezone`** (`string`)

**Request Body** (`application/x-www-form-urlencoded`):

- **`name`** (`string`)
- **`default_bank_account`** (`string`)
- **`timezone`** (`string`)

**Request Body** (`multipart/form-data`):

- **`name`** (`string`)
- **`default_bank_account`** (`string`)
- **`timezone`** (`string`)

**Response 200:** 

- **`username`** (`string`) *(required, read-only)* — Required. 150 characters or fewer. Letters, digits and @/./+/-/_ only.
- **`email`** (`string`) *(required, read-only)*
- **`name`** (`string`)
- **`url`** (`string`) *(required, read-only)*
- **`default_bank_account`** (`string`)
- **`timezone`** (`string`)
- **`has_usable_password`** (`boolean`) *(required, read-only)* — Return True if the user has a usable (non-unusable) password set.

#### `GET /api/v1/users/me/api-keys/`

**Operation:** `users_me_api_keys_list`

Return all API keys (active, expired, and revoked) belonging to the authenticated user.  Key material is never included -- only the displayable prefix.

**Parameters:**

- `page` (query, optional) — A page number within the paginated result set.
- `page_size` (query, optional) — Number of results to return per page.

**Response 200:** 

- **`count`** (`integer`) *(required)*
- **`next`** (`string`)
- **`previous`** (`string`)
- **`results`** (`array`) *(required)*

#### `POST /api/v1/users/me/api-keys/`

**Operation:** `users_me_api_keys_create`

Create a new API key for the authenticated user.  ``expiry_days`` sets the key's lifetime in days (the UI presets are 30 / 60 / 90 / 365); omit it or pass null for a key that never expires.

The response is the **only** time the plaintext ``key`` is returned; it cannot be recovered afterwards.

**Request Body** (`application/json`):

- **`name`** (`string`) *(required)*
- **`expiry_days`** (`integer`)

**Request Body** (`application/x-www-form-urlencoded`):

- **`name`** (`string`) *(required)*
- **`expiry_days`** (`integer`)

**Request Body** (`multipart/form-data`):

- **`name`** (`string`) *(required)*
- **`expiry_days`** (`integer`)

**Response 201:** 

- **`uuid`** (`string`) *(required, read-only)*
- **`name`** (`string`) *(required, read-only)* — User-supplied label identifying what this key is for.
- **`prefix`** (`string`) *(required, read-only)*
- **`expires_at`** (`string`) *(required, read-only)*
- **`last_used_at`** (`string`) *(required, read-only)*
- **`revoked_at`** (`string`) *(required, read-only)*
- **`created_at`** (`string`) *(required, read-only)*
- **`key`** (`string`) *(required, read-only)*

#### `GET /api/v1/users/me/api-keys/{uuid}/`

**Operation:** `users_me_api_keys_retrieve`

Return a single API key by its UUID.

**Parameters:**

- `uuid` (path, required)

**Response 200:** 

- **`uuid`** (`string`) *(required, read-only)*
- **`name`** (`string`) *(required, read-only)* — User-supplied label identifying what this key is for.
- **`prefix`** (`string`) *(required, read-only)*
- **`expires_at`** (`string`) *(required, read-only)*
- **`last_used_at`** (`string`) *(required, read-only)*
- **`revoked_at`** (`string`) *(required, read-only)*
- **`created_at`** (`string`) *(required, read-only)*

#### `POST /api/v1/users/me/api-keys/{uuid}/revoke/`

**Operation:** `users_me_api_keys_revoke_create`

Permanently revoke an API key.  Revoked keys stop authenticating immediately but remain listed for audit purposes.  Revocation cannot be undone.

**Parameters:**

- `uuid` (path, required)

**Response 200:** 

- **`uuid`** (`string`) *(required, read-only)*
- **`name`** (`string`) *(required, read-only)* — User-supplied label identifying what this key is for.
- **`prefix`** (`string`) *(required, read-only)*
- **`expires_at`** (`string`) *(required, read-only)*
- **`last_used_at`** (`string`) *(required, read-only)*
- **`revoked_at`** (`string`) *(required, read-only)*
- **`created_at`** (`string`) *(required, read-only)*

#### `POST /api/v1/users/me/change-email/`

**Operation:** `users_me_change_email_create`

Initiate a self-service email change.  Sends a verification link to the new address and a revocation link to the old address.  Returns 403 if the user has no usable password; 409 if new_email is already taken or a revocation window is currently open for this account.

**Request Body** (`application/json`):

- **`new_email`** (`string`) *(required)*

**Request Body** (`application/x-www-form-urlencoded`):

- **`new_email`** (`string`) *(required)*

**Request Body** (`multipart/form-data`):

- **`new_email`** (`string`) *(required)*

**Response 201:** No response body

#### `POST /api/v1/users/me/change-email/{token}/confirm/`

**Operation:** `users_me_change_email_confirm_create`

Verify a pending email change using the token from the verification link sent to the new address.  No authentication required -- the token is the credential.

**Dual-path note:** The email link points to a Django GET view at ``/users/email-change/{token}/confirm/`` which processes the action and redirects the browser to the SPA result page.  Native apps that register mibudge.money as a Universal Link (iOS) or App Link (Android) intercept that URL and call this endpoint instead, receiving JSON and controlling their own UI.

**Parameters:**

- `token` (path, required) — The email-change verification token.

**Response 200:** No response body

#### `POST /api/v1/users/me/change-email/{token}/revoke/`

**Operation:** `users_me_change_email_revoke_create`

Cancel a pending or recently confirmed email change using the token from the notification sent to the old address.  Valid for up to 7 days after confirmation.  No authentication required -- the token is the credential.

On post-confirmation revocation the email is reverted and all active sessions are invalidated.

**Dual-path note:** See ``change_email_confirm`` -- the same Universal Link / App Link pattern applies here.

**Parameters:**

- `token` (path, required) — The email-change revocation token.

**Response 200:** No response body

#### `POST /api/v1/users/me/change-password/`

**Operation:** `users_me_change_password_create`

Change the authenticated user's password. Requires the current password for verification. The new password must score at least 2 on the zxcvbn scale. Existing JWT tokens remain valid; the caller may silently refresh as normal -- no forced re-login is imposed.

**Request Body** (`application/json`):

- **`current_password`** (`string`) *(required)*
- **`new_password`** (`string`) *(required)*
- **`confirm_password`** (`string`) *(required)*

**Request Body** (`application/x-www-form-urlencoded`):

- **`current_password`** (`string`) *(required)*
- **`new_password`** (`string`) *(required)*
- **`confirm_password`** (`string`) *(required)*

**Request Body** (`multipart/form-data`):

- **`current_password`** (`string`) *(required)*
- **`new_password`** (`string`) *(required)*
- **`confirm_password`** (`string`) *(required)*

**Response 204:** No response body

#### `GET /api/v1/users/me/invitations/`

**Operation:** `users_me_invitations_list`

Return all pending co-ownership invitations sent by the authenticated user, across all accounts.

**Parameters:**

- `ordering` (query, optional) — Which field to use when ordering the results.
- `page` (query, optional) — A page number within the paginated result set.
- `page_size` (query, optional) — Number of results to return per page.

**Response 200:** 

- **`count`** (`integer`) *(required)*
- **`next`** (`string`)
- **`previous`** (`string`)
- **`results`** (`array`) *(required)*

## Schemas

### APIKey

Read serializer for API keys.

Never exposes the key material -- only the displayable prefix.  The
plaintext key appears exactly once, in the creation response (see
APIKeyViewSet.create).

- **`uuid`** (`string`) *(required, read-only)*
- **`name`** (`string`) *(required, read-only)* — User-supplied label identifying what this key is for.
- **`prefix`** (`string`) *(required, read-only)*
- **`expires_at`** (`string`) *(required, read-only)*
- **`last_used_at`** (`string`) *(required, read-only)*
- **`revoked_at`** (`string`) *(required, read-only)*
- **`created_at`** (`string`) *(required, read-only)*

### APIKeyCreateRequest

Validate an API-key creation request.

``expiry_days`` covers all the expiry presets (30 / 60 / 90 / 365 /
a specific number of days); null or omitted means the key never
expires.  The presets themselves are a UI concern.

- **`name`** (`string`) *(required)*
- **`expiry_days`** (`integer`)

### APIKeyCreated

Creation response -- the only place the plaintext key appears.

Exists to document the creation response shape in the OpenAPI
schema; the view assembles the payload itself.  ``key`` is never a
model field and cannot be recovered after this response.

- **`uuid`** (`string`) *(required, read-only)*
- **`name`** (`string`) *(required, read-only)* — User-supplied label identifying what this key is for.
- **`prefix`** (`string`) *(required, read-only)*
- **`expires_at`** (`string`) *(required, read-only)*
- **`last_used_at`** (`string`) *(required, read-only)*
- **`revoked_at`** (`string`) *(required, read-only)*
- **`created_at`** (`string`) *(required, read-only)*
- **`key`** (`string`) *(required, read-only)*

### AccountTypeEnum

* `C` - Checking
* `S` - Savings
* `X` - Credit Card


### Bank

Read-only serializer for banks.

Banks are shared reference data managed only through the admin.

- **`id`** (`string`) *(required, read-only)*
- **`name`** (`string`) *(required, read-only)*
- **`routing_number`** (`string`) *(required, read-only)*
- **`default_currency`** (`string`) *(required, read-only)* — ISO 4217 currency code (e.g. USD, EUR, GBP).
- **`created_at`** (`string`) *(required, read-only)*
- **`modified_at`** (`string`) *(required, read-only)*

### BankAccount

Serializer for bank accounts.

On create the caller supplies name, bank (UUID), account_type,
account_number, and optionally currency and initial balances.
The view routes creation through BankAccountService which adds
the requesting user as owner and seeds the Unallocated budget.

After creation, name and account_number are updatable.  Currency,
account_type, bank, and balances are immutable once the account
exists.

Group assignment is not yet supported via the API.

- **`id`** (`string`) *(required, read-only)*
- **`name`** (`string`) *(required)*
- **`bank`** (`string`) *(required)*
- **`owners`** (`array`) *(required, read-only)*
- **`account_type`** (`string`) — * `C` - Checking
* `S` - Savings
* `X` - Credit Card Enum: ['C', 'S', 'X']
- **`account_number`** (`string`)
- **`currency`** (`string`) — ISO 4217 currency code (e.g. USD, EUR, GBP).
- **`posted_balance`** (`string`)
- **`posted_balance_currency`** (`string`) *(required, read-only)*
- **`available_balance`** (`string`)
- **`available_balance_currency`** (`string`) *(required, read-only)*
- **`unallocated_budget`** (`string`) *(required, read-only)*
- **`auto_funding_enabled`** (`boolean`) — When enabled (the default), scheduled funding and recurrence events run automatically for this account.  Disable to opt out of automation and drive funding entirely from the 'Run funding now' button.
- **`last_imported_at`** (`string`) *(required, read-only)* — Wall-clock time of the most recent completed import for this account.
- **`last_posted_through`** (`string`) *(required, read-only)* — Latest posted_date seen in the most recent import batch. The funding engine will not process events dated after this value.
- **`created_at`** (`string`) *(required, read-only)*
- **`modified_at`** (`string`) *(required, read-only)*

### BankAccountInvitation

Read-only serializer for BankAccountInvitation rows.

``token`` is included so the SPA can construct the cancel URL without a
separate lookup.  It is safe to expose to authenticated account owners
since they created the invitation and the cancel endpoint enforces that
only the sender may cancel.

``bank_account_id`` and ``bank_account_name`` are included for the
cross-account listing on the user's settings page (me/invitations/).

- **`id`** (`string`) *(required, read-only)*
- **`token`** (`string`) *(required, read-only)*
- **`bank_account_id`** (`string`) *(required, read-only)*
- **`bank_account_name`** (`string`) *(required, read-only)*
- **`invitee_email`** (`string`) *(required, read-only)* — Email address the invitation was sent to. Immutable after creation.
- **`invited_by`** (`string`) *(required, read-only)*
- **`status`** (``) *(required, read-only)*
- **`expires_at`** (`string`) *(required, read-only)*
- **`accepted_at`** (`string`) *(required, read-only)*
- **`declined_at`** (`string`) *(required, read-only)*
- **`cancelled_at`** (`string`) *(required, read-only)*
- **`created_at`** (`string`) *(required, read-only)*
- **`modified_at`** (`string`) *(required, read-only)*

### BankAccountInvitationStatusEnum

* `pending` - Pending
* `accepted` - Accepted
* `declined` - Declined
* `cancelled` - Cancelled
* `expired` - Expired


### BankAccountRequest

Serializer for bank accounts.

On create the caller supplies name, bank (UUID), account_type,
account_number, and optionally currency and initial balances.
The view routes creation through BankAccountService which adds
the requesting user as owner and seeds the Unallocated budget.

After creation, name and account_number are updatable.  Currency,
account_type, bank, and balances are immutable once the account
exists.

Group assignment is not yet supported via the API.

- **`name`** (`string`) *(required)*
- **`bank`** (`string`) *(required)*
- **`account_type`** (`string`) — * `C` - Checking
* `S` - Savings
* `X` - Credit Card Enum: ['C', 'S', 'X']
- **`account_number`** (`string`)
- **`currency`** (`string`) — ISO 4217 currency code (e.g. USD, EUR, GBP).
- **`posted_balance`** (`string`)
- **`available_balance`** (`string`)
- **`auto_funding_enabled`** (`boolean`) — When enabled (the default), scheduled funding and recurrence events run automatically for this account.  Disable to opt out of automation and drive funding entirely from the 'Run funding now' button.

### BlankEnum


### Budget

Serializer for budgets.

On create the caller supplies bank_account (UUID) and budget
properties.  After creation, bank_account and budget_type are
immutable.  Balance is managed by signals and is always read-only.
The unallocated budget's name cannot be changed.

Currency is inherited from the bank account via the pre_save
signal and is not accepted from the client.

- **`id`** (`string`) *(required, read-only)*
- **`name`** (`string`) *(required)*
- **`bank_account`** (`string`) *(required)*
- **`balance`** (`string`) *(required, read-only)*
- **`balance_currency`** (`string`) *(required, read-only)*
- **`funded_amount`** (`string`) *(required, read-only)* — For Goal budgets: running net of all ITX credits minus debits. Unused for other types.
- **`funded_amount_currency`** (`string`) *(required, read-only)*
- **`target_balance`** (`string`) *(required)*
- **`target_balance_currency`** (`string`) *(required, read-only)*
- **`funding_amount`** (`string`)
- **`funding_amount_currency`** (`string`) *(required, read-only)*
- **`budget_type`** (`string`) — * `G` - Goal
* `R` - Recurring
* `A` - Associated Fill-up Goal
* `C` - Capped Enum: ['G', 'R', 'A', 'C']
- **`funding_type`** (`string`) — * `D` - Target Date
* `F` - Fixed Amount Enum: ['D', 'F']
- **`target_date`** (`string`)
- **`fillup_goal`** (`string`)
- **`archived`** (`boolean`) *(required, read-only)*
- **`archived_at`** (`string`) *(required, read-only)*
- **`complete`** (`boolean`) *(required, read-only)* — True when this budget has reached its target and should not be funded further.  Managed by signals and funding tasks; do not set manually.
- **`paused`** (`boolean`) — A paused budget does not get automatically funded on its schedule.
- **`funding_schedule`** (`string`)
- **`recurrence_schedule`** (`string`) — Refresh cycle for Recurring budgets.  Restricted grammar: a single RRULE whose FREQ is WEEKLY, MONTHLY, or YEARLY with an optional INTERVAL, plus an optional DTSTART that anchors the day the cycle refreshes on (e.g. 'DTSTART:20260708T000000Z RRULE:FREQ=MONTHLY' refreshes on the 8th of every month).  BY* parts, COUNT, UNTIL, and exception rules/dates are rejected -- the anchor date is the only day-of-cycle control.  The funding_schedule field is not restricted this way.
- **`memo`** (`string`)
- **`auto_spend`** (``) — List of matcher strings; currently transaction-category full names ('{group} : {name}').  Spend matching an entry is auto-routed to this budget.
- **`next_funding`** (`object`) *(required, read-only)* — Return the next scheduled funding event for this budget, or null.

Args:
    obj: The Budget instance being serialized.

Returns:
    Dict with 'date', 'amount', 'amount_currency', or None.
- **`next_recurrence`** (`string`) *(required, read-only)* — Return the date of the next recurrence (refresh) event, or null.

The recurrence_schedule's DTSTART is only the rule's anchor;
this field is the actual upcoming refresh date (first
occurrence after last_recurrence_on).  Only Recurring budgets
have one.

Args:
    obj: The Budget instance being serialized.

Returns:
    ISO date string, or None.
- **`funding_pace`** (``) *(required, read-only)*
- **`created_at`** (`string`) *(required, read-only)*
- **`modified_at`** (`string`) *(required, read-only)*

### BudgetRequest

Serializer for budgets.

On create the caller supplies bank_account (UUID) and budget
properties.  After creation, bank_account and budget_type are
immutable.  Balance is managed by signals and is always read-only.
The unallocated budget's name cannot be changed.

Currency is inherited from the bank account via the pre_save
signal and is not accepted from the client.

- **`name`** (`string`) *(required)*
- **`bank_account`** (`string`) *(required)*
- **`target_balance`** (`string`) *(required)*
- **`funding_amount`** (`string`)
- **`budget_type`** (`string`) — * `G` - Goal
* `R` - Recurring
* `A` - Associated Fill-up Goal
* `C` - Capped Enum: ['G', 'R', 'A', 'C']
- **`funding_type`** (`string`) — * `D` - Target Date
* `F` - Fixed Amount Enum: ['D', 'F']
- **`target_date`** (`string`)
- **`fillup_goal`** (`string`)
- **`paused`** (`boolean`) — A paused budget does not get automatically funded on its schedule.
- **`funding_schedule`** (`string`)
- **`recurrence_schedule`** (`string`) — Refresh cycle for Recurring budgets.  Restricted grammar: a single RRULE whose FREQ is WEEKLY, MONTHLY, or YEARLY with an optional INTERVAL, plus an optional DTSTART that anchors the day the cycle refreshes on (e.g. 'DTSTART:20260708T000000Z RRULE:FREQ=MONTHLY' refreshes on the 8th of every month).  BY* parts, COUNT, UNTIL, and exception rules/dates are rejected -- the anchor date is the only day-of-cycle control.  The funding_schedule field is not restricted this way.
- **`memo`** (`string`)
- **`auto_spend`** (``) — List of matcher strings; currently transaction-category full names ('{group} : {name}').  Spend matching an entry is auto-routed to this budget.

### BudgetTypeEnum

* `G` - Goal
* `R` - Recurring
* `A` - Associated Fill-up Goal
* `C` - Capped


### ChangePasswordRequest

Validate a password-change request.

Checks that the new password is strong enough (zxcvbn score >= 2)
and that the two new-password fields match.  Current-password
verification and the actual password update are handled in the view.

- **`current_password`** (`string`) *(required)*
- **`new_password`** (`string`) *(required)*
- **`confirm_password`** (`string`) *(required)*

### ChannelPreference

Channel delivery preference.

Read: channel, display_name, digest_frequency.
Write (PATCH): digest_frequency only.

- **`channel`** (`string`) *(required, read-only)*
- **`display_name`** (`string`) *(required, read-only)*
- **`digest_frequency`** (`string`) *(required)* — * `daily_morning` - Once daily (morning, ~7 am)
* `daily_evening` - Once daily (evening, ~6 pm)
* `twice_daily` - Twice daily (morning + evening)
* `weekly_friday` - Weekly on Friday
* `weekly_saturday` - Weekly on Saturday
* `weekly_sunday` - Weekly on Sunday Enum: ['daily_morning', 'daily_evening', 'twice_daily', 'weekly_friday', 'weekly_saturday', 'weekly_sunday']

### DeliveryModeEnum

* `digest` - Digest
* `immediate` - Immediate
* `off` - Off


### DigestFrequencyEnum

* `daily_morning` - Once daily (morning, ~7 am)
* `daily_evening` - Once daily (evening, ~6 pm)
* `twice_daily` - Twice daily (morning + evening)
* `weekly_friday` - Weekly on Friday
* `weekly_saturday` - Weekly on Saturday
* `weekly_sunday` - Weekly on Sunday


### EmailChangeRequestRequest

Validate a request to initiate an email-address change.

- **`new_email`** (`string`) *(required)*

### EmailTokenObtainPairRequest

TokenObtainPairSerializer variant that uses ``email`` as the login
field instead of ``username``.

USERNAME_FIELD is kept as "username" so Django admin is unaffected;
we override ``username_field`` here so simplejwt presents an ``email``
field in the login payload and passes it to EmailBackend.authenticate().

- **`email`** (`string`) *(required)*
- **`password`** (`string`) *(required)*

### FundingEventOccurrence

Read-only serializer for FundingEventOccurrence rows.

Exposes the budget UUID as 'budget' rather than the internal pkid so
callers can cross-reference with the Budget endpoint.

- **`id`** (`string`) *(required, read-only)*
- **`budget`** (`string`) *(required, read-only)*
- **`kind`** (`string`) *(required, read-only)* — Funding event discriminator: "fund" or "recur".  Stored as the EventKind string value; not exposed in user-facing forms so no choices= is set.
- **`scheduled_date`** (`string`) *(required, read-only)* — Calendar date the event was scheduled to fire.
- **`status`** (``) *(required, read-only)*
- **`completed_at`** (`string`) *(required, read-only)* — Wall-clock time the occurrence reached COMPLETE.  Null while PENDING/PARTIAL/SKIPPED.
- **`created_at`** (`string`) *(required, read-only)*
- **`modified_at`** (`string`) *(required, read-only)*

### FundingEventStatusEnum

* `PENDING` - Pending
* `PARTIAL` - Partial
* `COMPLETE` - Complete
* `SKIPPED` - Skipped


### FundingPaceEnum

* `ahead` - ahead
* `on_track` - on_track
* `behind` - behind


### FundingTypeEnum

* `D` - Target Date
* `F` - Fixed Amount


### InternalTransaction

Serializer for internal transactions (budget-to-budget transfers).

Internal transactions are write-once: the API supports create and
read but not update or delete.  To reverse a transfer, create a
new internal transaction with the src and dst budgets swapped.

On create the caller supplies bank_account, amount, src_budget,
and dst_budget.  The view sets the actor to the requesting user.

The ``amount_currency`` is read from raw request data by
djmoney's ``MoneyField.get_value()`` -- no explicit currency
field declaration is needed.

- **`id`** (`string`) *(required, read-only)*
- **`bank_account`** (`string`) *(required)*
- **`amount`** (`string`) *(required)*
- **`amount_currency`** (`string`) *(required, read-only)*
- **`src_budget`** (`string`) *(required)*
- **`dst_budget`** (`string`) *(required)*
- **`actor`** (`integer`) *(required, read-only)*
- **`effective_date`** (`string`)
- **`src_budget_balance`** (`string`) *(required, read-only)*
- **`src_budget_balance_currency`** (`string`) *(required, read-only)*
- **`dst_budget_balance`** (`string`) *(required, read-only)*
- **`dst_budget_balance_currency`** (`string`) *(required, read-only)*
- **`created_at`** (`string`) *(required, read-only)*
- **`modified_at`** (`string`) *(required, read-only)*

### InternalTransactionRequest

Serializer for internal transactions (budget-to-budget transfers).

Internal transactions are write-once: the API supports create and
read but not update or delete.  To reverse a transfer, create a
new internal transaction with the src and dst budgets swapped.

On create the caller supplies bank_account, amount, src_budget,
and dst_budget.  The view sets the actor to the requesting user.

The ``amount_currency`` is read from raw request data by
djmoney's ``MoneyField.get_value()`` -- no explicit currency
field declaration is needed.

- **`bank_account`** (`string`) *(required)*
- **`amount`** (`string`) *(required)*
- **`src_budget`** (`string`) *(required)*
- **`dst_budget`** (`string`) *(required)*
- **`effective_date`** (`string`)

### InviteOwnerRequest

Write-only serializer for the invite-owner action.

- **`invitee_email`** (`string`) *(required)*

### NotificationPreference

Notification kind preference.

Read: kind, display_name, can_suppress, delivery_mode.
Write (PATCH): delivery_mode only (rejected for can_suppress=False kinds).

- **`kind`** (`string`) *(required, read-only)*
- **`display_name`** (`string`) *(required, read-only)*
- **`can_suppress`** (`boolean`) *(required, read-only)*
- **`delivery_mode`** (`string`) *(required)* — * `digest` - Digest
* `immediate` - Immediate
* `off` - Off Enum: ['digest', 'immediate', 'off']

### NullEnum


### PaginatedAPIKeyList

- **`count`** (`integer`) *(required)*
- **`next`** (`string`)
- **`previous`** (`string`)
- **`results`** (`array`) *(required)*

### PaginatedBankAccountInvitationList

- **`count`** (`integer`) *(required)*
- **`next`** (`string`)
- **`previous`** (`string`)
- **`results`** (`array`) *(required)*

### PaginatedBankAccountList

- **`count`** (`integer`) *(required)*
- **`next`** (`string`)
- **`previous`** (`string`)
- **`results`** (`array`) *(required)*

### PaginatedBankList

- **`count`** (`integer`) *(required)*
- **`next`** (`string`)
- **`previous`** (`string`)
- **`results`** (`array`) *(required)*

### PaginatedBudgetList

- **`count`** (`integer`) *(required)*
- **`next`** (`string`)
- **`previous`** (`string`)
- **`results`** (`array`) *(required)*

### PaginatedChannelPreferenceList

- **`count`** (`integer`) *(required)*
- **`next`** (`string`)
- **`previous`** (`string`)
- **`results`** (`array`) *(required)*

### PaginatedFundingEventOccurrenceList

- **`count`** (`integer`) *(required)*
- **`next`** (`string`)
- **`previous`** (`string`)
- **`results`** (`array`) *(required)*

### PaginatedInternalTransactionList

- **`count`** (`integer`) *(required)*
- **`next`** (`string`)
- **`previous`** (`string`)
- **`results`** (`array`) *(required)*

### PaginatedNotificationPreferenceList

- **`count`** (`integer`) *(required)*
- **`next`** (`string`)
- **`previous`** (`string`)
- **`results`** (`array`) *(required)*

### PaginatedTransactionAllocationList

- **`count`** (`integer`) *(required)*
- **`next`** (`string`)
- **`previous`** (`string`)
- **`results`** (`array`) *(required)*

### PaginatedTransactionCategoryList

- **`count`** (`integer`) *(required)*
- **`next`** (`string`)
- **`previous`** (`string`)
- **`results`** (`array`) *(required)*

### PaginatedTransactionList

- **`count`** (`integer`) *(required)*
- **`next`** (`string`)
- **`previous`** (`string`)
- **`results`** (`array`) *(required)*

### PaginatedUserList

- **`count`** (`integer`) *(required)*
- **`next`** (`string`)
- **`previous`** (`string`)
- **`results`** (`array`) *(required)*

### PatchedBankAccountRequest

Serializer for bank accounts.

On create the caller supplies name, bank (UUID), account_type,
account_number, and optionally currency and initial balances.
The view routes creation through BankAccountService which adds
the requesting user as owner and seeds the Unallocated budget.

After creation, name and account_number are updatable.  Currency,
account_type, bank, and balances are immutable once the account
exists.

Group assignment is not yet supported via the API.

- **`name`** (`string`)
- **`bank`** (`string`)
- **`account_type`** (`string`) — * `C` - Checking
* `S` - Savings
* `X` - Credit Card Enum: ['C', 'S', 'X']
- **`account_number`** (`string`)
- **`currency`** (`string`) — ISO 4217 currency code (e.g. USD, EUR, GBP).
- **`posted_balance`** (`string`)
- **`available_balance`** (`string`)
- **`auto_funding_enabled`** (`boolean`) — When enabled (the default), scheduled funding and recurrence events run automatically for this account.  Disable to opt out of automation and drive funding entirely from the 'Run funding now' button.

### PatchedBudgetRequest

Serializer for budgets.

On create the caller supplies bank_account (UUID) and budget
properties.  After creation, bank_account and budget_type are
immutable.  Balance is managed by signals and is always read-only.
The unallocated budget's name cannot be changed.

Currency is inherited from the bank account via the pre_save
signal and is not accepted from the client.

- **`name`** (`string`)
- **`bank_account`** (`string`)
- **`target_balance`** (`string`)
- **`funding_amount`** (`string`)
- **`budget_type`** (`string`) — * `G` - Goal
* `R` - Recurring
* `A` - Associated Fill-up Goal
* `C` - Capped Enum: ['G', 'R', 'A', 'C']
- **`funding_type`** (`string`) — * `D` - Target Date
* `F` - Fixed Amount Enum: ['D', 'F']
- **`target_date`** (`string`)
- **`fillup_goal`** (`string`)
- **`paused`** (`boolean`) — A paused budget does not get automatically funded on its schedule.
- **`funding_schedule`** (`string`)
- **`recurrence_schedule`** (`string`) — Refresh cycle for Recurring budgets.  Restricted grammar: a single RRULE whose FREQ is WEEKLY, MONTHLY, or YEARLY with an optional INTERVAL, plus an optional DTSTART that anchors the day the cycle refreshes on (e.g. 'DTSTART:20260708T000000Z RRULE:FREQ=MONTHLY' refreshes on the 8th of every month).  BY* parts, COUNT, UNTIL, and exception rules/dates are rejected -- the anchor date is the only day-of-cycle control.  The funding_schedule field is not restricted this way.
- **`memo`** (`string`)
- **`auto_spend`** (``) — List of matcher strings; currently transaction-category full names ('{group} : {name}').  Spend matching an entry is auto-routed to this budget.

### PatchedChannelPreferenceRequest

Channel delivery preference.

Read: channel, display_name, digest_frequency.
Write (PATCH): digest_frequency only.

- **`digest_frequency`** (`string`) — * `daily_morning` - Once daily (morning, ~7 am)
* `daily_evening` - Once daily (evening, ~6 pm)
* `twice_daily` - Twice daily (morning + evening)
* `weekly_friday` - Weekly on Friday
* `weekly_saturday` - Weekly on Saturday
* `weekly_sunday` - Weekly on Sunday Enum: ['daily_morning', 'daily_evening', 'twice_daily', 'weekly_friday', 'weekly_saturday', 'weekly_sunday']

### PatchedNotificationPreferenceRequest

Notification kind preference.

Read: kind, display_name, can_suppress, delivery_mode.
Write (PATCH): delivery_mode only (rejected for can_suppress=False kinds).

- **`delivery_mode`** (`string`) — * `digest` - Digest
* `immediate` - Immediate
* `off` - Off Enum: ['digest', 'immediate', 'off']

### PatchedTransactionCategoryRequest

Serializer for transaction categories.

On create the caller supplies group and name; the view forces the
owner to the requesting user (global rows are managed via the
django-admin only).  Group and name are whitespace-normalized and
checked case-insensitively against the global rows and the user's
own rows for duplicates.  'archived' is toggled via the archive
action, not writable here.

- **`group`** (`string`)
- **`name`** (`string`)

### PatchedTransactionRequest

Serializer for bank transactions.

On create the caller supplies bank_account, amount,
transaction_date, transaction_type, raw_description, and
optionally pending, memo, and description.

After creation only transaction_type, memo, and description are
updatable.  The view is responsible for creating the default
TransactionAllocation to the unallocated budget on create.

The ``amount_currency`` is read from raw request data by
djmoney's ``MoneyField.get_value()`` -- no explicit currency
field declaration is needed.

- **`bank_account`** (`string`)
- **`amount`** (`string`)
- **`posted_date`** (`string`)
- **`transaction_date`** (`string`)
- **`transaction_type`** (``)
- **`pending`** (`boolean`)
- **`memo`** (`string`)
- **`raw_description`** (`string`)
- **`description`** (`string`)
- **`category`** (`string`)
- **`merchant_address`** (`string`)
- **`merchant_city`** (`string`)
- **`merchant_region`** (`string`)
- **`merchant_country`** (`string`)
- **`merchant_latitude`** (`string`)
- **`merchant_longitude`** (`string`)
- **`bank_transaction_id`** (`string`)
- **`image`** (`string`)
- **`document`** (`string`)

### PatchedUserRequest

Serializer for user profiles.

The ``default_bank_account`` field is writable but constrained:
the bank account must be owned by the user being updated.  On
output it returns the UUID string (or null).

``has_usable_password`` is read-only and used by the SPA to decide
whether to enable the change-email and change-password forms.

- **`name`** (`string`)
- **`default_bank_account`** (`string`)
- **`timezone`** (`string`)

### PublicInvitationDetail

Read-only serializer for the public invitation-detail endpoint.

Returns the minimum information needed to render the acceptance page
for API clients.  Owner names are intentionally minimal (display name
or email only) to limit PII exposure behind a bare token.

- **`id`** (`string`) *(required, read-only)*
- **`status`** (``) *(required, read-only)*
- **`invitee_email`** (`string`) *(required, read-only)* — Email address the invitation was sent to. Immutable after creation.
- **`bank_account_name`** (`string`) *(required, read-only)*
- **`bank_name`** (`string`) *(required, read-only)*
- **`current_owners`** (`array`) *(required, read-only)*
- **`is_new_user`** (`boolean`) *(required, read-only)*
- **`expires_at`** (`string`) *(required, read-only)*

### ResolvePendingRequest

Input serializer for the resolve-pending action.

Validates the settled posted_date and optional final amount.
Requires ``transaction`` in the serializer context for sign validation.

- **`posted_date`** (`string`) *(required)*
- **`amount`** (`string`)

### ScrapeSyncDetailsNeeded

One posted scrape row still needing a transaction-details fetch.

`index` is the row's position in the SUBMITTED transactions array
(exact correlation back to the scraper's own rows); `transaction`
is the DB row the fetched details should be applied to via the
transaction-details action.

- **`index`** (`integer`) *(required)*
- **`transaction`** (`string`) *(required)*

### ScrapeSyncReport

Output serializer for the bank-account scrape-sync action.

Mirrors `service.sync_scrape.ScrapeSyncReport`.  Reports
everything the caller needs to summarise what changed and surface
validation warnings.

- **`deleted_pending`** (`integer`) *(required)*
- **`inserted_posted`** (`integer`) *(required)*
- **`skipped_posted`** (`integer`) *(required)*
- **`inserted_pending`** (`integer`) *(required)*
- **`balance_mismatch`** (`string`) *(required)*
- **`posting_order_mismatches`** (`array`) *(required)*
- **`last_posted_through`** (`string`) *(required)*
- **`new_transaction_ids`** (`array`) *(required)*
- **`details_needed`** (`array`) *(required)*

### ScrapeSyncRequest

Input serializer for the bank-account scrape-sync action.

Validates a full bank-side snapshot for one account: when the
scrape was taken, the bank's ending available balance, and the
list of transactions (newest-first as the bank renders them).

- **`scraped_at`** (`string`) *(required)*
- **`ending_balance`** (`string`) *(required)*
- **`transactions`** (`array`) *(required)*

### ScrapeSyncTransactionRequest

One transaction in a scrape-sync payload.

Mirrors `service.sync_scrape.ScrapedTransaction`.  Pending rows
carry the scrape's local `posted_date` (banks typically render
pending rows without a real settlement date -- e.g. BofA shows
'Processing' in the date column -- and the scraper substitutes
the current local datetime).  Posted rows carry the bank-supplied
settlement datetime.  `transaction_date` is derived server-side
from the embedded MM/DD pattern in `raw_description`.

`running_balance` is optional and used only for the posting-order
sanity walk; never persisted.

- **`is_pending`** (`boolean`) *(required)*
- **`posted_date`** (`string`) *(required)*
- **`raw_description`** (`string`) *(required)*
- **`amount`** (`string`) *(required)*
- **`transaction_type`** (`string`)
- **`running_balance`** (`string`)

### TokenRefresh

- **`access`** (`string`) *(required, read-only)*
- **`refresh`** (`string`) *(required)*

### TokenRefreshRequest

- **`refresh`** (`string`) *(required)*

### Transaction

Serializer for bank transactions.

On create the caller supplies bank_account, amount,
transaction_date, transaction_type, raw_description, and
optionally pending, memo, and description.

After creation only transaction_type, memo, and description are
updatable.  The view is responsible for creating the default
TransactionAllocation to the unallocated budget on create.

The ``amount_currency`` is read from raw request data by
djmoney's ``MoneyField.get_value()`` -- no explicit currency
field declaration is needed.

- **`id`** (`string`) *(required, read-only)*
- **`bank_account`** (`string`) *(required)*
- **`amount`** (`string`) *(required)*
- **`amount_currency`** (`string`) *(required, read-only)*
- **`party`** (`string`) *(required, read-only)*
- **`posted_date`** (`string`) *(required)*
- **`transaction_date`** (`string`)
- **`transaction_type`** (``) *(required)*
- **`pending`** (`boolean`)
- **`memo`** (`string`)
- **`raw_description`** (`string`) *(required)*
- **`description`** (`string`)
- **`description_user_edited`** (`boolean`) *(required, read-only)*
- **`category`** (`string`)
- **`category_full_name`** (`string`) *(required, read-only)*
- **`merchant_name`** (`string`) *(required, read-only)*
- **`merchant_address`** (`string`)
- **`merchant_city`** (`string`)
- **`merchant_region`** (`string`)
- **`merchant_country`** (`string`)
- **`merchant_latitude`** (`string`)
- **`merchant_longitude`** (`string`)
- **`merchant_category`** (`string`) *(required, read-only)*
- **`merchant_category_code`** (`string`) *(required, read-only)*
- **`virtual_card_number`** (`string`) *(required, read-only)*
- **`has_details`** (`boolean`) *(required, read-only)*
- **`bank_transaction_id`** (`string`)
- **`linked_transaction`** (`string`) *(required, read-only)*
- **`bank_account_posted_balance`** (`string`) *(required, read-only)* — Posted Balance does not include pending debits.
- **`bank_account_posted_balance_currency`** (`string`) *(required, read-only)*
- **`bank_account_available_balance`** (`string`) *(required, read-only)* — Available Balance has pending debits deducted.
- **`bank_account_available_balance_currency`** (`string`) *(required, read-only)*
- **`image`** (`string`)
- **`document`** (`string`)
- **`created_at`** (`string`) *(required, read-only)*
- **`modified_at`** (`string`) *(required, read-only)*

### TransactionAllocation

Serializer for transaction allocations.

An allocation maps a portion of a transaction's amount to a budget.
On create the caller supplies transaction, amount, and optionally
budget (defaults to unallocated) and category.  After creation,
budget, category, and memo are updatable.

The serializer enforces two key constraints:

1. **Same-account restriction** -- the budget must belong to the
   same bank account as the transaction.  Cross-account allocations
   are rejected with a 400 error.
2. **Sum constraint** -- the total allocated amount across all
   allocations for a transaction must not exceed the transaction
   amount.

The ``amount_currency`` is read from raw request data by
djmoney's ``MoneyField.get_value()`` -- no explicit currency
field declaration is needed.

- **`id`** (`string`) *(required, read-only)*
- **`transaction`** (`string`) *(required)*
- **`budget`** (`string`)
- **`amount`** (`string`) *(required)*
- **`amount_currency`** (`string`) *(required, read-only)*
- **`budget_balance`** (`string`) *(required, read-only)*
- **`budget_balance_currency`** (`string`) *(required, read-only)*
- **`category`** (`string`)
- **`category_full_name`** (`string`) *(required, read-only)*
- **`memo`** (`string`)
- **`created_at`** (`string`) *(required, read-only)*
- **`modified_at`** (`string`) *(required, read-only)*

### TransactionCategory

Serializer for transaction categories.

On create the caller supplies group and name; the view forces the
owner to the requesting user (global rows are managed via the
django-admin only).  Group and name are whitespace-normalized and
checked case-insensitively against the global rows and the user's
own rows for duplicates.  'archived' is toggled via the archive
action, not writable here.

- **`id`** (`string`) *(required, read-only)*
- **`group`** (`string`) *(required)*
- **`name`** (`string`) *(required)*
- **`full_name`** (`string`) *(required, read-only)* — Canonical display form: '{group} : {name}'.
- **`owner`** (`string`) *(required, read-only)* — Owner username; null for a global category.
- **`archived`** (`boolean`) *(required, read-only)* — Archived categories are hidden from pickers but remain valid on existing transactions and allocations.
- **`created_at`** (`string`) *(required, read-only)*
- **`modified_at`** (`string`) *(required, read-only)*

### TransactionCategoryRequest

Serializer for transaction categories.

On create the caller supplies group and name; the view forces the
owner to the requesting user (global rows are managed via the
django-admin only).  Group and name are whitespace-normalized and
checked case-insensitively against the global rows and the user's
own rows for duplicates.  'archived' is toggled via the archive
action, not writable here.

- **`group`** (`string`) *(required)*
- **`name`** (`string`) *(required)*

### TransactionDetailsItemRequest

One (transaction, raw details dict) pair to apply.

The details dict is stored verbatim on the transaction (it is the
provenance record); the service extracts the merchant columns and
the category hint from it.

- **`transaction`** (`string`) *(required)*
- **`details`** (`object`) *(required)*

### TransactionDetailsReport

Output serializer for the bank-account transaction-details action.

- **`applied`** (`integer`) *(required)*
- **`skipped_has_details`** (`integer`) *(required)*
- **`skipped_pending`** (`integer`) *(required)*
- **`not_found`** (`integer`) *(required)*
- **`results`** (`array`) *(required)*

### TransactionDetailsRequest

Input serializer for the bank-account transaction-details action.

`overwrite` re-applies scraper-owned fields on rows already
enriched (location fields and an assigned category are still
never clobbered).

- **`overwrite`** (`boolean`)
- **`details`** (`array`) *(required)*

### TransactionDetailsResult

Per-item outcome of the transaction-details action.

- **`transaction`** (`string`) *(required)*
- **`status`** (`string`) *(required)* — * `applied` - applied
* `skipped_has_details` - skipped_has_details
* `skipped_pending` - skipped_pending
* `not_found` - not_found Enum: ['applied', 'skipped_has_details', 'skipped_pending', 'not_found']
- **`warnings`** (`array`) *(required)*

### TransactionDetailsResultStatusEnum

* `applied` - applied
* `skipped_has_details` - skipped_has_details
* `skipped_pending` - skipped_pending
* `not_found` - not_found


### TransactionRequest

Serializer for bank transactions.

On create the caller supplies bank_account, amount,
transaction_date, transaction_type, raw_description, and
optionally pending, memo, and description.

After creation only transaction_type, memo, and description are
updatable.  The view is responsible for creating the default
TransactionAllocation to the unallocated budget on create.

The ``amount_currency`` is read from raw request data by
djmoney's ``MoneyField.get_value()`` -- no explicit currency
field declaration is needed.

- **`bank_account`** (`string`) *(required)*
- **`amount`** (`string`) *(required)*
- **`posted_date`** (`string`) *(required)*
- **`transaction_date`** (`string`)
- **`transaction_type`** (``) *(required)*
- **`pending`** (`boolean`)
- **`memo`** (`string`)
- **`raw_description`** (`string`) *(required)*
- **`description`** (`string`)
- **`category`** (`string`)
- **`merchant_address`** (`string`)
- **`merchant_city`** (`string`)
- **`merchant_region`** (`string`)
- **`merchant_country`** (`string`)
- **`merchant_latitude`** (`string`)
- **`merchant_longitude`** (`string`)
- **`bank_transaction_id`** (`string`)
- **`image`** (`string`)
- **`document`** (`string`)

### TransactionSplitsRequest

Serializer for the declarative splits endpoint.

Accepts a dict mapping budget UUIDs to amounts.  The backend
reconciles existing allocations to match the declared state.
Any remainder goes to the unallocated budget.

All budgets must belong to the same bank account as the
transaction.  Cross-account budget references are rejected
with a 400 error.

- **`splits`** (`object`) *(required)* — Map of budget UUID → amount.  Amounts must not exceed the transaction total.  Omitted remainder is assigned to the unallocated budget.

### TransactionTypeEnum

* `signature_purchase` - Signature Purchase
* `ach` - ACH
* `round-up_transfer` - Round-up Transfer
* `protected_goal_account_transfer` - Protected Goal Account Transfer
* `fee` - Fee
* `pin_purchase` - Pin Purchase
* `signature_credit` - Signature Credit
* `interest_credit` - Interest Credit
* `shared_transfer` - Shared Transfer
* `courtesy_credit` - Courtesy Credit
* `atm_withdrawal` - ATM Withdrawal
* `bill_payment` - Bill Payment
* `bank_generated_credit` - Bank Generated Credit
* `wire_transfer` - Wire Transfer
* `check_deposit` - Check Deposit
* `check` - Check
* `c2c` - c2c
* `migration_interbank_transfer` - Migration Interbank Transfer
* `balance_sweep` - Balance Sweep
* `ach_reversal` - ACH Reversal
* `adjustment` - Adjustment
* `signature_return` - Signature return
* `fx_order` - FX Order
* `` - --------


### User

Serializer for user profiles.

The ``default_bank_account`` field is writable but constrained:
the bank account must be owned by the user being updated.  On
output it returns the UUID string (or null).

``has_usable_password`` is read-only and used by the SPA to decide
whether to enable the change-email and change-password forms.

- **`username`** (`string`) *(required, read-only)* — Required. 150 characters or fewer. Letters, digits and @/./+/-/_ only.
- **`email`** (`string`) *(required, read-only)*
- **`name`** (`string`)
- **`url`** (`string`) *(required, read-only)*
- **`default_bank_account`** (`string`)
- **`timezone`** (`string`)
- **`has_usable_password`** (`boolean`) *(required, read-only)* — Return True if the user has a usable (non-unusable) password set.

### UserRequest

Serializer for user profiles.

The ``default_bank_account`` field is writable but constrained:
the bank account must be owned by the user being updated.  On
output it returns the UUID string (or null).

``has_usable_password`` is read-only and used by the SPA to decide
whether to enable the change-email and change-password forms.

- **`name`** (`string`)
- **`default_bank_account`** (`string`)
- **`timezone`** (`string`)

