# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.4.3] - 2026-10-29

No migrations: going back to 0.4.2 needs no database change.

### Fixed

- The live BofA importer signs in and reads bank accounts again after Bank of America redesigned its site (bofa_scraper 1.2.0); `--timeout` is now the pause after each transaction details dialog

## [0.4.2] - 2026-10-25

No migrations: going back to 0.4.1 needs no database change.

### Added

- Docker images for `linux/arm64` alongside `linux/amd64`, under the same tags

## [0.4.1] - 2026-10-19

One migration, `moneypools.0044`, which changes only a help text: going back to 0.4.0 needs no database change.

### Added

- `GET /api/version/` reports the release the server runs and the API versions it serves, without signing in, and every API response names the release in an `X-Mibudge-Version` header. The OpenAPI schema's version and the landing page's footer show the release too
- The SPA declares the server releases it supports and offers a reload when the server runs another one (as after a deploy), and the settings page shows the SPA's release, the server releases it supports and the server's release. The API reference recommends how other clients check the server's release
- `define_budgets --as-of DATE` creates and updates budgets as if DATE were today, so budgets defined for a simulation fund on the simulated clock without a hand-written `DTSTART`

### Fixed

- `define_budgets --dry-run` lists each schedule's next dates, as documented; it printed none
- After a deploy, a tab opened before it no longer fails to open a page it had not visited yet: it loads that page fresh, running the new release. The SPA shell is sent with `Cache-Control: no-cache`, so every page load gets the current release
- The description of a bank account's `last_posted_through` no longer claims that funding stops at that date: funding does not read it. Migration `moneypools.0044` changes only the field's help text and makes no database changes

## [0.4.0] - 2026-10-16

### Added

- The SPA keeps open pages current: returning to a tab after a minute away, or coming back online, refetches what the page shows in the background (no flashing, scrolled lists stay as deep as you scrolled, edits in progress are kept, and a record that has gone away says so), and pulling down from the top of the page or pressing Refresh in the side navigation refetches it on demand
- "Revoke all keys" in Security & Notifications settings revokes every active API key at once, after a confirmation that says how many (`POST /api/v1/users/me/api-keys/revoke-all/`)
- Transaction list and detail responses embed each transaction's allocations, and `GET /api/v1/transactions/` takes `budget` (transactions with an allocation to that budget) and `unallocated` (nothing assigned to a real budget) filters, so a budget's transactions page from the server in one request
- SPA keyboard and touch accessibility: a visible focus outline on every control, focus kept inside open sheets, 44px touch targets, and delete buttons you can reach on a phone
- SPA "page not found" screen for unknown `/app/...` paths, instead of a blank page
- `simulate_bank_activity` management command fills a development instance with simulated banks, bank accounts and realistic transactions (split paychecks, bills, card spending, pending purchases that later post, transfers within and between banks, credit card payments, interest, Federal Reserve holidays) from an editable scenario file, and steps a simulated clock forward day by day, running budget funding on the simulated dates. See `docs/simulator.md`

### Changed

- SPA look: text and controls meet WCAG AA contrast (darker primary and destructive buttons, stronger input borders and muted text), with one button shape and consistent sizes, spacing and padding throughout; text honours the browser's text-size setting, and phone inputs no longer zoom the page when focused
- SPA transaction lists load page by page with each row's budgets included: a budget's transactions scroll in as needed, and the "Unallocated" filter covers the bank account's whole history instead of only the loaded rows
- SPA dates display in one consistent format everywhere, set in a single place so it can become a user preference
- The API reference (`docs/api.md`) is rewritten for client developers: common responses, pagination and throttling (with how to pace a throttled client) are described once, bodies are commented JSON with each field's type, shared objects are defined once and linked, and complex endpoints have worked examples. The OpenAPI schema documents every endpoint's error responses
- The production deployment template moved to `deployment/production/`; its Celery broker and results use their own Redis databases, and it no longer requires a `telegraf_network`. Its `VERSION` names a release (`0.4.0`): published images have no `latest` tag. `docs/releasing.md` describes versions, release tags and the published images
- Local development uses one `.env` per host, created from `deployment/dot-env.dev` by `make up`, and a per-host mkcert certificate in `deployment/ssl/`, so several machines can share one checkout. `deployment/local-dev-docker.env` and `HOST_SSL_DIR` are no longer used; regenerate an existing `.env` with `mv .env .env.old && make env`. See `deployment/README.md`
- `.python-version` is checked in and names the project's Python version (3.13.16), which CI tests on and release images are built with; `make lint` installs a pre-commit hook that runs through `uv run`, so it works on every machine sharing a checkout
- SPA development: a Vitest test suite against a mock REST API (`pnpm test`, `make test-frontend`; see `docs/spa/testing.md`), API types generated from `docs/openapi.yaml` (`pnpm gen:api-types`), oxlint and a design-token style check (`pnpm lint`, `pnpm lint:styles`), all run in CI and pre-commit, and architecture, state, component and screen documentation in `docs/spa/`

### Removed

- The SPA's "Last 30 days" transaction filter; the list already starts at today and loads older transactions as you scroll

### Fixed

- Two concurrent changes to the same budget or bank account (for example two imports or two transfers at once) could lose one of the updates. Balance updates now re-read the row under a database lock held until the request commits
- Work that ran longer than 30 seconds while holding a Redis lock (a large bank sync, deleting a budget with a long history) could lose the lock partway through, letting a second worker start the same bank account's funding run or sync, and then failed with a 500. Held locks are now renewed until the work finishes, and a lock that is lost anyway is logged instead of failing the request
- Resolving a pending transaction twice at once could credit the bank account's posted balance twice, and resolving one to a different date with an unchanged amount left the Unallocated budget's running balances out of order
- Deleting a Recurring budget discarded its fill-up goal's balance instead of returning it to Unallocated, so the bank account's budgets no longer added up to its available balance. Deleting a budget now also reverses its transfers with other budgets, and is refused when the fill-up goal has transaction allocations
- On SQLite, two concurrent writers no longer fail with "database is locked" (every transaction opens with `BEGIN IMMEDIATE`, so they wait for each other), and API reads (GET/HEAD) no longer run inside a transaction, so they neither wait for nor block a request that is writing
- Money amounts always take their bank account's currency: an omitted `<field>_currency` means the bank account's currency rather than the server default, and a different currency is refused with 400 (it was silently overwritten, stored, or failed with a 500 when amounts were added up). A bank account created without `currency` takes its bank's default currency, as documented
- Creating or editing a budget with a funding type or target date its budget type does not allow answers 400 naming the field instead of a 500, and creating one without `funding_type` or `budget_type` takes the defaults (Goal, Target Date) instead of failing with a 500; the SPA's budget form asks for a target amount instead of showing a bare "HTTP 400"
- The OpenAPI schema matches the API: the splits, invitation-list and notification/channel-preference endpoints are plain arrays without phantom pagination, previously untyped responses and fields are typed, and nullable fields are marked. The notification/channel preference endpoints answer an unknown kind or channel with a `{"detail": ...}` 404 instead of an empty body
- Returning to a tab after the access token expired could sign you out ("Session expired") even though your session was valid, because several requests refreshed the token at once; concurrent refreshes now share one request
- When your session expires mid-use, the SPA returns you to the sign-in page and, after signing in, back to the page you were on
- Signing out clears every cached bank account, budget, allocation and list position in the tab, so nothing from the previous session is shown to the next person to sign in
- Calendar dates (budget target dates, next-refresh and funding dates) showed one day early in browsers west of UTC, and transaction list date headers did when the browser's timezone differed from your profile's; dates now show the same day everywhere. A transaction's date and time in a non-English browser no longer joins them with an English "at"
- The SPA kept showing the previous record after navigating: a link from one budget to another, switching bank accounts quickly (which could show the previous bank account's transactions), switching bank accounts on a budget or transaction page (which now goes to that section's list), and a transaction opened from another bank account (which showed the active bank account's name and its Unallocated split as a budget assignment)
- On a transaction's page: editing the description or memo and quickly stepping to the next transaction could save the text onto the next one, clearing the memo did not save, a failed receipt upload was silently ignored, and previous / next stepped through transactions hidden by the list's filter and search
- The split editor accepted fractions of a cent and saved them rounded up, so a split shown as fully allocated could exceed the transaction by a cent and be rejected; it now checks the amounts it will save
- The transaction list could show stale or missing budget assignments after a bank sync or a co-owner's re-split until you signed out, and the "Unallocated" filter listed every transaction while they loaded
- Failed actions and page loads in the SPA say why, using the server's message, where several failed silently or showed fixed text (memo and description saves, splits, loading more transactions, with a "Try again", invitations, settings, deleting a bank account); "Could not reach the server" now appears only when a request got no response
- Settings that save as soon as you change them always end showing what the server saved: a refused change, or a quick second change while the first is saving, no longer leaves the control showing a value the server does not have
- The production `.env` example sets `ALLOWED_HOSTS`; it named `DJANGO_ALLOWED_HOSTS`, which the server ignores, so a deployment following it rejected every request to its own host name
- The production deployment guide's rollback steps reverse a release's migrations with that release's image before switching to the previous version; the `migrate` service only migrates forward, so starting an older image left the newer schema in place

### Security

- Creating a budget, transaction or internal transaction checked only that the named bank account existed, not that you owned it, so any signed-in user or API key that knew another bank account's UUID could create objects in it and change its balances. These endpoints now accept only bank accounts you own (one you do not own gets the same 400 "does not exist" as a nonexistent one), and re-check ownership of every bank-account-owned object in the request. A budget's `fillup_goal` is now read-only in the API
- Sign-in is rate-limited per client address and per email address, so password guessing is slowed even when spread across many addresses; a browser that has signed in to that email before has its own limit, so someone guessing cannot lock you out of it. Password changes are limited per user and token refreshes per address. Over a limit the request answers 429 and the sign-in page says how long to wait. Rates are set with `DJANGO_THROTTLE_<SCOPE>` (see `deployment/production/dot-env.example`)
- Rate limits identify anonymous clients by the address the deployment's own proxies report, so a client can no longer get a fresh limit by sending its own `X-Forwarded-For`; set `DJANGO_TRUSTED_PROXY_COUNT` to the number of reverse proxies in front of Django (see `deployment/production/dot-env.example`)
- Signing out ends the session on the server: `POST /api/token/logout/` revokes the refresh token and clears its cookie, so reloading the page or reopening the app no longer signs you straight back in
- Changing your password signs out every other session (the device you changed it on stays signed in), and completing a password reset signs out every session. The reset email lists your active API keys so you can revoke any you do not recognise; requesting a reset changes nothing until the emailed link is used. A newly invited user setting their first password gets a welcome page with a sign-in link instead
- Cancelling an email change signs out every session. Cancelling one that was already confirmed (account takeover recovery) also revokes every API key and says how many; cancelling one before it was confirmed lists your active API keys so you can revoke any you do not recognise
- API keys can no longer delete a bank account (which deletes everything in it); `DELETE /api/v1/bank-accounts/{id}/` requires an interactive login and answers 403 to an API key

## [0.3.0] - 2026-07-24

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
- Release images are published to `ghcr.io/scanner/mibudge` tagged with their version (`0.3.0`, and `0.3.0-dev` for the development image) and labelled with it (`org.opencontainers.image.version`); `make build` tags local images the same way, and `make publish-tag` signs and pushes a release tag. Images are no longer published to Docker Hub

### Fixed

- Password-reset emails (including the set-your-first-password email sent when a new invitee accepts an invitation) linked to the deployment's internal hostname instead of `SITE_URL`; allauth-generated URLs are now rooted at `SITE_URL` like all other emailed links

### Security

- Published Docker images no longer carry a build-time `SALT_KEY` in their layer history; building an image needs no secret (`docker build` takes no `SALT_KEY` build argument)

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

[Unreleased]: https://github.com/scanner/mibudge/compare/0.4.3...HEAD
[0.4.3]: https://github.com/scanner/mibudge/compare/0.4.2...0.4.3
[0.4.2]: https://github.com/scanner/mibudge/compare/0.4.1...0.4.2
[0.4.1]: https://github.com/scanner/mibudge/compare/0.4.0...0.4.1
[0.4.0]: https://github.com/scanner/mibudge/compare/0.3.0...0.4.0
[0.3.0]: https://github.com/scanner/mibudge/compare/0.2.0...0.3.0
[0.2.0]: https://github.com/scanner/mibudge/compare/0.1.1...0.2.0
[0.1.1]: https://github.com/scanner/mibudge/compare/0.1.0...0.1.1
[0.1.0]: https://github.com/scanner/mibudge/releases/tag/0.1.0
