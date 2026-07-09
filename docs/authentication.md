# Authentication

mibudge supports two ways to authenticate against the REST API:

| Method             | Credential                          | Intended for                                              |
|--------------------|-------------------------------------|-----------------------------------------------------------|
| **Password + JWT** | `Authorization: Bearer <access>`    | Interactive user agents: the SPA, mobile and desktop apps |
| **API key**        | `Authorization: Api-Key <key>`      | Machine clients: transaction importers, 3rd-party services |

OAuth2 for registered third-party apps (hosted import services, MCP
servers) is planned as the next phase of machine authentication.

---

## Interactive sessions: the JWT two-token pattern

- **Access token** (60 min): held in JS memory only, sent as
  `Authorization: Bearer` header.
- **Refresh token** (14 days, sliding): `httpOnly; Secure; SameSite=Strict`
  cookie, never readable by JS.
- **Rotation**: `ROTATE_REFRESH_TOKENS = True`,
  `BLACKLIST_AFTER_ROTATION = True` -- each refresh call resets the 14-day
  clock.
- **Login flow**: the SPA owns its own auth UI at `/app/login/`. It posts
  email+password to `POST /api/token/` (`CookieTokenObtainPairView`), which
  returns the access token in the JSON body and sets the refresh token as
  the `httpOnly; Secure; SameSite=Strict` cookie.
- **Cold-boot silent refresh**: on first load, `main.ts` calls
  `authStore.refresh()` before installing the router. If the refresh cookie
  is still valid, the SPA becomes authenticated before the first route guard
  runs and returning users skip the login screen entirely.
- **Silent refresh on 401**: when the access token expires, the auth store
  calls `POST /api/token/refresh/` -- the browser sends the httpOnly cookie
  automatically, returning a new access token and rotating the refresh
  cookie.
- **django-allauth**: remains mounted at `/accounts/` for password reset
  only (`/accounts/password/reset/`); it is not part of the SPA login path.
  The allauth templates are plain Django-rendered pages -- they do not use
  the SPA shell.

### Passwordless accounts

Users created via the bank-account co-ownership invitation flow are issued
a JWT session immediately but have no password set
(`has_usable_password() == False`). They can use the app normally but
cannot use the change-password or change-email features until they set a
password via `/accounts/password/reset/`. Both forms detect this state via
the `has_usable_password` field on `GET /api/v1/users/me/` and prompt the
user accordingly.

### Self-service email change

Users can change their login email address via a verified two-step flow. A
7-day post-confirmation revocation window lets the legitimate owner cancel
even if an attacker confirmed the change first, with automatic session
invalidation on revocation. See `users/email_change.py` for the security
policy.

---

## Machine credentials: API keys

API keys let 3rd-party services (and the importers in `importers/`) call
the REST API on a user's behalf without holding the user's password.

### Creating and managing keys

Keys are managed at `/api/v1/users/me/api-keys/` (or in the SPA under
Settings -> API keys):

| Endpoint                                        | Action                                          |
|-------------------------------------------------|--------------------------------------------------|
| `POST /api/v1/users/me/api-keys/`               | Create a key (`name`, optional `expiry_days`)   |
| `GET /api/v1/users/me/api-keys/`                | List your keys (active, expired, and revoked)   |
| `GET /api/v1/users/me/api-keys/{uuid}/`         | Retrieve one key                                 |
| `POST /api/v1/users/me/api-keys/{uuid}/revoke/` | Permanently revoke a key                         |

- **Expiry**: `expiry_days` sets the key lifetime in days (UI presets:
  30 / 60 / 90 / 365, or any custom number); omit it for a key that never
  expires.
- **Plaintext once**: the creation response is the only place the plaintext
  key appears. Only a SHA-256 hash is stored; a lost key cannot be
  recovered, only replaced.
- **Prefix**: every key starts with `mib_`; the list endpoints expose the
  first characters (e.g. `mib_AbCd1234`) so a key in the UI can be matched
  against the one you hold.
- **Revocation**: keys are soft-revoked -- they stop authenticating
  immediately but remain listed for audit. Revocation cannot be undone.
- **Usage tracking**: `last_used_at` is updated on authenticated use
  (throttled to one write per `API_KEY_LAST_USED_THROTTLE`, default 5
  minutes, so bulk imports don't write on every request).

### Using a key

Send the plaintext key on every request:

```
Authorization: Api-Key mib_...
```

The importer CLIs accept `--api-key`, the `MIBUDGE_API_KEY` environment
variable, a 1Password item's `API key` field
(`--api-key-onepassword-url` / `MIBUDGE_API_KEY_ONEPASSWORD_URL`), or a
Vault secret key `api_key` -- see
[`docs/importers.md`](importers.md).

### What API keys may not do

Machine credentials get blanket access to the budgeting domain (bank
accounts, budgets, transactions, allocations, funding, ...) but are
**denied** on user/security endpoints:

- password change, email change
- co-ownership invitations (send, list, cancel)
- user management (`/api/v1/users/`, including `PATCH /users/me/`)
- API-key management itself (a key cannot mint or revoke keys)

The one carve-out: `GET /api/v1/users/me/` **is** allowed for machine
credentials. It returns only profile facts (no security levers), and the
importers need the `timezone` field to anchor bank-statement dates
correctly. Writes to the profile remain interactive-only.

This is enforced by the `users.permissions.RequiresInteractiveAuth`
permission -- a blocklist gate attached to those views -- and its
read-only variant `RequiresInteractiveAuthForWrites` (used on
`/users/me/`, gating only mutating methods). When fine-grained scopes are
introduced, these gates become scopes (e.g. the read carve-out maps to a
`profile:read` scope). **When adding a new sensitive user/security
endpoint, attach `RequiresInteractiveAuth` to it; use
`RequiresInteractiveAuthForWrites` only when machine consumers genuinely
need the reads.**

### Implementation

| Piece                  | Location                                        |
|------------------------|--------------------------------------------------|
| `APIKey` model         | `app/users/models.py`                            |
| DRF authentication     | `app/users/authentication.py` (`ApiKeyAuthentication`) |
| Interactive-auth gate  | `app/users/permissions.py` (`RequiresInteractiveAuth`) |
| Management endpoints   | `app/users/api/v1/views.py` (`APIKeyViewSet`)    |
| Client support         | `importers/client.py` (`MibudgeClient(api_key=...)`) |

NOTE: the stored digest is an unsalted SHA-256 of the plaintext -- safe
because the secret is a high-entropy random token (not a low-entropy
password), and a deterministic hash allows an indexed O(1) lookup on every
authenticated request.
