REST API for the mibudge personal budgeting service.  Every versioned
endpoint is under `/api/v1/`; the token endpoints are under `/api/token/`
and the version endpoint is `/api/version/`.

## Versions

`GET /api/version/` answers the release the server runs and the API
versions it serves, and needs no credentials:

```json
{"version": "0.4.1", "api_versions": ["v1"]}
```

Every `/api/` response, errors included, carries the release in an
`X-Mibudge-Version` header.

Releases follow semantic versioning.  Before 1.0, a breaking change to
the API is made in `/api/v1/` itself and bumps the minor version.  At
1.0, `/api/v1/` is frozen: from then on a breaking change ships as a new
`/api/vN/` alongside the existing ones, so a client moves to it when it
is ready, and removing an `/api/vN/` is a major release.

### Checking the server's release

Minor and patch releases can fix the API's behaviour as well as add to
it, so a client may depend on a particular release, not only on an API
version.  Whether to check is the client's choice.  To check:

- Declare the server releases the client supports as a semver range,
  e.g. `>=0.5.2 <0.7.0`.  The lower bound is the first release with the
  behaviour the client relies on; the upper bound is the first release
  that may break it: the next minor release before 1.0, the next major
  release from 1.0.
- Read the server's release from `GET /api/version/` at startup, or
  from the `X-Mibudge-Version` header of any response, which also
  notices a server upgraded while the client runs.  Check that
  `api_versions` lists the API version the client uses.
- When the release is outside the range, the client decides what to
  do: warn, turn off what may not work, or stop.  A release that is not
  semver (a development server reports `unknown`) is best treated as
  supported.

The CHANGELOG lists each release's API changes.  The browser app is
released with the server and supports exactly the release that serves
it; when the two differ it offers to reload.

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
there.  `GET /api/version/` ignores credentials altogether.

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
the number of results, $page_size by default and at most $max_page_size.  Follow `next` until it is `null`.

## Throttling

Requests are rate-limited per caller:

- **Authenticated** (access token or API key): $throttle_user per user.  All of a user's API keys and sessions share the one budget.
- **Anonymous** (login and the public endpoints): $throttle_anon per client address.
- **Login** (`POST /api/token/`), on top of the anonymous limit: $throttle_login per client address, and $throttle_login_email per email address.  A browser that has signed in to that email before carries a device cookie, and its attempts count against a separate $throttle_login_device instead of the per-email limit.
- **Token refresh** (`POST /api/token/refresh/`): $throttle_token_refresh per client address.
- **Password change**: $throttle_password_change per user, on top of the authenticated limit.

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
