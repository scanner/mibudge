# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Transaction categories are now a shared, extensible model instead of a fixed enum: a global base set everyone shares, plus custom categories you can create that are visible to anyone you co-own a bank account with. Managed at `/api/v1/transaction-categories/` (create, rename, archive; delete is blocked while a category is still in use -- archive instead). See `docs/transaction-categories.md`
- Transactions and their splits each carry a category; a split inherits the transaction's category when it's created and can then be changed independently
- Category hints from bank imports are translated into your categories by the importer (built-in BofA mapping plus a `--category-map` overlay file for newly discovered categories); categories the importer cannot map are reported at the end of each run and their transactions left unassigned for you to categorize
- Transactions can carry merchant details: merchant name, structured location (street address, city, region, country, and map coordinates -- the location fields are user-editable so you can refine or supply a merchant's actual address), the ISO 18245 merchant category code, and the masked virtual card number used. New transaction filters: `merchant_name`, `merchant_city`, `merchant_region`, `merchant_category_code`, `virtual_card_last4`, `has_details`
- Purchases routed through a payment platform (Square, Toast, DoorDash, and others) now show the real store instead of the platform's card-network prefix, with the platform itself recorded separately and noted in the description ("Blue Bottle Coffee -- Menlo Park, CA (Restaurants, via DoorDash)"); filter transactions by platform with `merchant_intermediary`. The platform list is admin-editable and reorderable, so a newly observed platform needs no code release. `reenrich_merchant_identity` refreshes already-enriched transactions from their stored details with no re-scrape
- The BofA live importer enriches posted transactions from BofA's per-transaction detail dialog: the importer-mapped category auto-categorizes the transaction (and its unassigned splits), and the display description becomes "Merchant -- City, ST (Category)". Detail fetches are budgeted (`--details-limit`, default 30 dialog opens per run) and each merchant is fetched only once per run -- its other transactions get a free provenance-marked copy -- so a backfill converges over a couple of weeks of runs without tripping BofA's rate limits
- `POST /api/v1/bank-accounts/{id}/transaction-details/` applies scraped detail records; `sync-scrape` responses report `details_needed` so importers know exactly which rows still need enrichment
- Saved scrape files (format v3) include fetched details and `import_bofa_saved` replays them; `--save-only --details-all` captures every detail dialog for offline import
- Editing a transaction's description now marks it user-edited, so detail enrichment never overwrites your text
- SPA test harness: Vitest + happy-dom with an MSW mock REST API, DTO factories, auth and mounting fixtures, and tests for the transport, auth/token lifecycle, stores, API modules, utilities, router guard and views. `pnpm test` / `pnpm test:coverage` (coverage thresholds on `src/api`, `src/composables`, `src/domain`, `src/models`, `src/stores`), `make test-frontend`, and a Drone `frontend tests` step. See `docs/spa/testing.md`
- SPA TypeScript types for the REST API are generated from `docs/openapi.yaml` (`pnpm gen:api-types`, openapi-typescript); the Drone `frontend lint` step fails when `frontend/src/api/schema.d.ts` is out of date
- SPA "page not found" screen for unknown `/app/...` paths, instead of a blank page
- SPA architecture documentation in `docs/spa/`: the layers and their import rules (`architecture.md`), the HTTP transport, errors, types and models (`api-and-models.md`), stores and caching (`state.md`), components (`components.md`), and a recipe for adding a page (`adding-a-page.md`); an architecture test enforces the layering on every test run

### Changed

- Transaction and allocation APIs expose `category` (a category UUID) with a read-only `category_full_name`; transactions can be filtered by `category`, `category_group`, and `uncategorized`. **Breaking:** the allocation `category` filter now takes a category UUID instead of the old enum string
- `Budget.auto_spend` entries are validated against the categories visible to you and stored as canonical `"{group} : {name}"` names
- Internal: split moneypools API views and serializers into per-domain modules
- Internal: the SPA is restructured into layers -- pure domain rules (money, dates, schedules, budget status), an HTTP transport and per-resource API modules, domain models mapped from the API's wire format, Pinia entity caches, shared composables, and per-section feature modules -- and the five largest views are split into route shells of under 300 lines. No visual changes except the date fix below
- Signing out now clears every cached bank account, budget, allocation and list position in the tab, so nothing from the previous session is shown to the next person to sign in
- When your session expires mid-use, the SPA now returns you to the sign-in page and, after signing in, back to the page you were on
- A SQLite database now opens every transaction with `BEGIN IMMEDIATE`, so two concurrent writers wait for each other instead of the second failing with "database is locked"; the test suite uses a SQLite file with the same setting and runs the concurrency tests on both SQLite and Postgres
- API read requests (GET/HEAD) no longer run inside a database transaction; writes still run each request in one, rolled back on any error. On SQLite, reads therefore no longer wait for, or block, a request that is writing

### Fixed

- Creating a budget without `funding_type` or `budget_type` returned a 500; the omitted fields now take the model defaults (Goal, Target Date)
- Password-reset emails (including the set-your-first-password email sent when a new invitee accepts an invitation) linked to the deployment's internal hostname instead of `SITE_URL`; allauth-generated URLs are now rooted at `SITE_URL` like all other emailed links
- Budget target dates, next-refresh dates and funding dates showed one day early in browsers west of UTC (a goal due Dec 14 read "Dec 13"); calendar dates now show the same day in every timezone. Transaction list date headers had the same problem when the browser's timezone differed from your profile timezone
- Editing a transaction's description or memo and then quickly stepping to the next transaction could save the text onto the next transaction
- Clearing a transaction's memo did not save
- A failed receipt/document upload on a transaction was silently ignored; it now shows an error
- Following a link from one budget's page to another budget kept showing the first budget
- Previous / next on a transaction stepped through transactions hidden by the list's filter and search
- Switching bank accounts quickly could show the previous account's transactions
- The transaction list could show stale or missing budget assignments after a bank sync or a co-owner's re-split until you signed out; it now refreshes them on every visit, and the "Unallocated" filter no longer lists every transaction while they load
- Failed actions and page loads in the SPA now say why, using the server's message: failed memo/description saves (which reverted silently), failed splits, removing a transaction from a budget, loading more transactions (with a "Try again"), cancelling invitations, the default-account and automatic-funding settings, deleting a bank account, and the bank list; transfers, pause/archive and notification/API-key errors show the server's reason instead of fixed text
- Creating a budget without a target amount failed with a bare "HTTP 400"; the form now asks for a target
- The split editor accepted amounts with fractions of a cent, checked them unrounded but saved them rounded up, so a split it showed as fully allocated could exceed the transaction by a cent and be rejected; it now checks the amounts it will save
- A transaction opened from another bank account (for example by a link) showed the active account's name and listed its Unallocated split as a budget assignment
- Switching bank accounts on a budget or transaction page kept showing the previous account's budget or transaction; it now goes to that section's list for the new account
- In the SPA, an error in the app itself was reported as "Could not reach the server. Check your connection."; only a request that got no response now shows that message
- A transaction's date and time in a non-English browser read like "Dienstag, 15. Oktober 2024 at 14:34"; the word joining them is now in the browser's language too
- Settings that save as soon as you change them now always end showing what the server saved: a refused email-digest change no longer keeps showing the new frequency, a quick second delivery-mode change is no longer undone when an earlier one fails, and toggling automatic funding twice quickly no longer flips the switch back while the second change is saving
- Returning to a tab after the access token expired could log you out ("Session expired") even though your session was valid: several requests refreshed the token at once, and every refresh after the first was rejected because the backend had already rotated the refresh cookie. Concurrent refreshes now share a single request
- Two concurrent changes to the same budget or bank account (for example two imports or two transfers at once) could lose one of the updates: the service layer released its lock before the request's database transaction committed, so the second writer read the stale balance and overwrote the first. Balance updates now re-read the row under a database lock held until commit (a row lock on Postgres, the database write lock on SQLite)
- Work that ran longer than 30 seconds while holding a Redis lock (a large bank sync, deleting a budget with a long history) could lose the lock partway through, letting a second worker start the same account's funding run or sync, and then failed with a 500 when it tried to release the lock. Held locks are now renewed in the background until the work finishes, and a lock that is lost anyway is logged instead of failing the request
- Resolving the same pending transaction twice at once (or updating it to posted twice) could credit the account's posted balance twice; the second attempt now sees the transaction is already posted
- Resolving a pending transaction to a different date with an unchanged amount left the Unallocated budget's running balances out of order; they are now recalculated from the earlier of the two dates
- Deleting a Recurring budget discarded its fill-up goal's balance instead of returning it to Unallocated, so the account's budgets no longer added up to its available balance. Deleting a budget now also reverses its transfers with other budgets and recalculates their running balances, and is refused when the fill-up goal has transaction allocations

### Security

- Creating a budget, transaction or internal transaction checked only that the named bank account existed, not that you owned it, so any logged-in user or API key that knew another account's UUID could create objects in it and change its balances. The `bank_account` field on these create endpoints now accepts only accounts you own (an account you do not own gets the same 400 "does not exist" error as a nonexistent one), and the views re-check ownership of every account-owned object in the request before creating anything. A budget's `fillup_goal` is now read-only in the API; the budget service manages it

## [0.2.0] - 2026-07-12

### Added

- API keys: long-lived machine credentials for importers and 3rd-party services (`Authorization: Api-Key <key>`), managed at `/api/v1/users/me/api-keys/` with optional expiry (30/60/90/365 days, custom, or never); the plaintext key is shown only once at creation
- Machine credentials are denied access to user/security endpoints (password/email change, invitations, user management, key management) -- these require an interactive login; `GET /api/v1/users/me/` is exempt so importers can read the user's timezone
- Importer CLIs accept `--api-key` / `MIBUDGE_API_KEY` (or Vault key `api_key`), preferred over email/password
- Account settings page: manage API keys (create with expiry, one-time key display, revoke)
- Email notice when an API key will expire within the next 14 days (configurable via `API_KEY_EXPIRY_NOTICE_DAYS`), sent once per key so a replacement can be minted before importers and other services lose access
- Importer CLIs can source the API key used to authenticate to mibudge from a 1Password secret reference (`op://<vault>/<item>[/<section>]/<field>`) via `--api-key-onepassword-url` / `MIBUDGE_API_KEY_ONEPASSWORD_URL`
- Bank-account co-ownership invitations: staff can resend a pending invitation from the Django admin (previously only cancel was available)
- Documentation for the invitation flows (`docs/invitations.md`) and the self-service email-change flow (`docs/email-change.md`): mechanism, rate limiting, and security policy
- Server-computed `funding_pace` field on the Budget API (`ahead` / `on_track` / `behind`, null when not applicable): goal pace measured by amount funded against scheduled funding events elapsed, so spending out of a goal (even into a negative balance) never reads as behind pace

### Changed

- BofA live scraper's 1Password credential flag renamed `--onepassword-url` → `--bofa-onepassword-url` (env var `ONEPASSWORD_URL` → `BOFA_ONEPASSWORD_URL`), so its name says which credential it fetches instead of a generic name
- Funding schedules are now anchored server-side with a DTSTART on the first date the schedule actually fires (set at budget creation; re-figured when the funding dates or goal date are edited), making funding-event enumeration deterministic; a django migration will update existing budgets that need a DTSTART

### Fixed

- Goal budgets on a funding schedule without a DTSTART counted a phantom funding event when spreading the remaining gap, shrinking every deposit and leaving the goal under-funded at its target date (e.g. $366 per event instead of $549)
- "Behind pace" badge now measures goal progress by the amount funded (matching the funding engine) instead of the current balance, so spending out of a goal no longer marks it behind pace; the Budget API exposes the new read-only `funded_amount` field
- Importer CLIs crashed with `FileNotFoundError` when the repo-root `.env` set app-only variables like `SSL_CERT_FILE`; they now load only importer-related variables (`MIBUDGE_*`, `BOFA_*`, `VAULT_*`) from `.env`
- `POST /api/v1/bank-accounts/{id}/invite/` returned a 500 when the per-address invitation rate limit was hit; it now returns 429 Too Many Requests with a descriptive message
- The public invitation accept/decline endpoints were missing from the generated OpenAPI schema (`make api-docs` reported errors); they and the token-parameterized invitation/email-change endpoints are now fully documented, the no-body POST endpoints no longer advertise a bogus request body, and the three `status` enums have stable names instead of hash-suffixed ones

## [0.1.1] - 2026-07-03

### Added

- `next_recurrence` field on the Budget API: the actual upcoming refresh date for Recurring budgets, computed from the schedule and the last processed recurrence

### Changed

- Recurring budget wording unified on "refresh" (was a mix of "resets", "next due", and "Refresh cycle"); budget detail now shows a "Next refresh" row
- `recurrence_schedule` on the Budget API is now restricted to a simple cycle grammar: one RRULE (WEEKLY/MONTHLY/YEARLY with optional INTERVAL) anchored by an optional DTSTART; BY* parts, COUNT, UNTIL, and exception rules/dates are rejected with a 400. `funding_schedule` keeps the full grammar

### Fixed

- Recurring budgets displayed the schedule's original anchor date as "next due" (e.g. "next due May 1, 2026" months after May 1); the next refresh date is now computed from the last processed recurrence, and the edit form is prefilled with it
- Editing a recurring budget's refresh date could leave a stale day-of-month in the stored rule, making the budget refresh on the old day while the UI claimed the new one; the saved rule is now anchored solely by the chosen date, and schedule descriptions reflect the day the rule actually fires

- Immediate notifications (e.g. new pending transactions) were silently dropped when the Celery worker picked up the task before the request transaction committed (`ATOMIC_REQUESTS=True`); task dispatch now uses `on_commit` so it is enqueued only after the transaction commits
- Funding events no longer stall when the Unallocated budget has a negative balance caused by pending transactions; the full intended amount now always transfers (Unallocated may go negative) so recurring budgets are fully funded even across payroll-pending boundaries

## [0.1.0] - 2026-06-07

### Added

- Budget management with Goal, Recurring, and Recurring-with-fill-up-goal types
- Transaction allocation: assign any portion of a transaction to a budget; split transactions across multiple budgets
- Internal budget-to-budget transfers within an account; reversible by creating a counterpart transfer
- Transaction import via OFX/QFX files; FITID-based deduplication prevents re-importing the same transaction
- Bank of America live-scraping importer for automated transaction retrieval
- Link counterpart transactions across accounts (e.g. credit card payment on checking paired with the credit on the card)
- Automatic budget funding on a configurable recurrence schedule (weekly, bi-weekly, monthly, etc.)
- Funding summary banner showing next funding amounts and dates per budget
- Funding events displayed in the user's local timezone
- Joint bank accounts: invite a co-owner by email; invitation acceptance issues a session directly
- Email-address-as-username: the login credential is the user's email address
- Self-service password change from the account page
- Self-service email change with 24-hour verification link and 7-day post-confirmation revocation window
- Email notifications: password changed, password reset, import errors, and co-ownership invitations
- Notification delivery preferences: digest, immediate, or off; per-notification-kind opt-in/out
- Vue 3 TypeScript SPA with Pinia state management and JWT silent-refresh auth
- Production Docker image: nginx + gunicorn + supervisord, frontend SPA compiled and baked in
- Drone CI pipeline: lint (ruff/mypy/vue-tsc), pytest, Docker image build and publish to GHCR and Docker Hub

[Unreleased]: https://github.com/scanner/mibudge/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/scanner/mibudge/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/scanner/mibudge/releases/tag/v0.1.0
