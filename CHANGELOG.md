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

### Changed

- Transaction and allocation APIs expose `category` (a category UUID) with a read-only `category_full_name`; transactions can be filtered by `category`, `category_group`, and `uncategorized`. **Breaking:** the allocation `category` filter now takes a category UUID instead of the old enum string
- `Budget.auto_spend` entries are validated against the categories visible to you and stored as canonical `"{group} : {name}"` names

### Fixed

- Password-reset emails (including the set-your-first-password email sent when a new invitee accepts an invitation) linked to the deployment's internal hostname instead of `SITE_URL`; allauth-generated URLs are now rooted at `SITE_URL` like all other emailed links

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
