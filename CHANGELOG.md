# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- Importer CLIs crashed with `FileNotFoundError` when the repo-root `.env` set app-only variables like `SSL_CERT_FILE`; they now load only importer-related variables (`MIBUDGE_*`, `BOFA_*`, `VAULT_*`, `ONEPASSWORD_URL`) from `.env`

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
