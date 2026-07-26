# Authentication

mibudge supports three ways to authenticate against the REST API:

| Method             | Credential                          | Intended for                                              |
|--------------------|-------------------------------------|-----------------------------------------------------------|
| **Password + JWT** | `Authorization: Bearer <access>`    | Interactive user agents: the SPA, mobile and desktop apps |
| **API key**        | `Authorization: Api-Key <key>`      | Machine clients you run yourself: transaction importers   |
| **OAuth2 token**   | `Authorization: Bearer <access>`    | Registered third-party apps and MCP servers acting for a user |

The difference between the last two is who holds the secret. An API key
is minted by the user and pasted into something they operate. An OAuth2
grant is what a *third party* gets: the user authorizes an app without
ever handing it a credential, and can revoke it later.

Both are **machine credentials** and are treated identically by the
`RequiresInteractiveAuth` gate described below.

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

Users created via the invitation flows (bank-account co-ownership or
admin user invitations -- see [`invitations.md`](invitations.md)) start
with no password set (`has_usable_password() == False`). Accepting an
invitation activates the account and sends an allauth password-reset
email so the user sets their first password via
`/accounts/password/reset/`; acceptance never issues credentials
directly. While an account has no usable password, the change-password
and change-email endpoints refuse to operate. The SPA detects this
state via the `has_usable_password` field on `GET /api/v1/users/me/`
and prompts the user accordingly.

### Self-service email change

Users can change their login email address via a verified two-step flow. A
7-day post-confirmation revocation window lets the legitimate owner cancel
even if an attacker confirmed the change first, with automatic session
invalidation on revocation. See [`email-change.md`](email-change.md) for
the full flow and security policy.

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
- **Expiry notice**: a daily task emails the owner once when a key's
  expiry falls within the next `API_KEY_EXPIRY_NOTICE_DAYS` days
  (default 14), leaving time to mint and roll out a replacement. Keys
  cannot be renewed -- create a new key and revoke the old one.
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
variable, a 1Password secret reference to the field holding the key
(`--api-key-onepassword-url` / `MIBUDGE_API_KEY_ONEPASSWORD_URL`), or a
Vault secret key `api_key` -- see
[`docs/importers.md`](importers.md).

### What machine credentials may not do

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

This is enforced by the `credentials.permissions.RequiresInteractiveAuth`
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
| `APIKey` model         | `app/credentials/models.py`                      |
| DRF authentication     | `app/credentials/authentication.py` (`ApiKeyAuthentication`) |
| Interactive-auth gate  | `app/credentials/permissions.py` (`RequiresInteractiveAuth`) |
| Management endpoints   | `app/credentials/api/v1/views.py` (`APIKeyViewSet`) |
| Client support         | `importers/client.py` (`MibudgeClient(api_key=...)`) |

NOTE: the stored digest is an unsalted SHA-256 of the plaintext -- safe
because the secret is a high-entropy random token (not a low-entropy
password), and a deterministic hash allows an indexed O(1) lookup on every
authenticated request.

---

## Delegated access: OAuth2 for registered apps

Third-party apps -- MCP servers, hosted import services, future
integrations -- get access through an OAuth2 authorization-code grant
rather than by being handed a credential. The user approves the app once
on a consent screen; the grant then persists until they revoke it.

**Only one flow is offered: authorization code + PKCE, plus refresh
tokens.** No implicit, no resource-owner password, no client
credentials, and (for now) no device flow. This covers desktop, mobile
and MCP clients, all of which are public clients that cannot keep a
secret.

### Endpoints

| Endpoint | Purpose |
|----------|---------|
| `/.well-known/oauth-authorization-server` | RFC 8414 discovery document -- how a client finds the rest |
| `/o/authorize/` | Consent screen (server-rendered) |
| `/o/token/` | Code exchange and refresh |
| `/o/revoke_token/` | Revocation |
| `/o/login/` | **The OAuth2 flow's own login page** -- see below |

Endpoints DOT ships that are deliberately **not** mounted: the device
flow (`/o/device*`), DOT's own HTML app/token management screens, OIDC
(`userinfo`, `jwks.json`), dynamic client registration, and token
introspection. See the module docstring in
[`app/credentials/urls.py`](../app/credentials/urls.py) for why each one
is out.

### IMPORTANT: the OAuth2 flow has its own login page

`/o/login/` is a **separate login page from the SPA's** `/app/login/`,
and that is deliberate.

The consent screen needs `request.user`, which means it needs a **Django
session**. Nothing else in mibudge uses one: the SPA authenticates with
a JWT and API-key clients never see a login page at all. Pointing the
consent screen at the SPA login would deadlock -- the SPA would
authenticate the user, hand back a JWT, set no session cookie, and the
consent screen would bounce the user back to the login page forever.

So the OAuth2 flow gets a server-rendered login of its own. It takes the
**same email and password** as the SPA; only the artifact differs (a
session instead of a JWT), and that session exists only to carry the
user through consent.

This also matches the traffic: someone landing on `/o/authorize/` got
there from a third-party app, not from a mibudge tab, so there is
usually no SPA session to reuse anyway.

Practical consequences:

- Signing in at `/o/login/` does **not** sign you in to the SPA, and
  vice versa.
- `/o/login/` has a brute-force limit of its own
  (`OAUTH2_LOGIN_MAX_ATTEMPTS` failures per `OAUTH2_LOGIN_WINDOW_SECONDS`,
  counted per submitted email address) because DRF's throttling does not
  apply to a plain Django view.
- allauth's login view is **not** used: with
  `ACCOUNT_EMAIL_VERIFICATION = "mandatory"` it refuses any account
  without a verified allauth `EmailAddress` row, and this project never
  creates those.

### Token lifetimes and rotation

| Setting | Value | Why |
|---------|-------|-----|
| Access token | 60 min | Mirrors the SPA's JWT. DOT's 10-hour default is far too generous for a credential reaching a user's whole financial history. |
| Refresh token | No expiry | A grant ends by revocation, not by a timer -- that is the point of OAuth2 here. |
| Rotation | On every use | A captured refresh token is single-use and its reuse is detectable. |
| Reuse protection | On | Replaying a rotated-out refresh token revokes the whole token family. |
| Grace period | 120 s | A client whose refresh response is lost in flight can retry instead of losing the grant. |

NOTE: reuse protection makes DOT deliberately **retain** revoked refresh
tokens -- they are the record that makes replay detectable -- so those
rows accumulate at roughly one per refresh per grant.

It also rules out hashed token storage
(`COMPLIANT_BCP_RFC9700_TOKEN_STORAGE`): honouring a rotated-out refresh
token means returning the previously issued token, which a hash cannot
reproduce. That is a deliberate trade-off of at-rest protection for
refresh reliability, and it is the one place OAuth2 tokens are stored
differently from API keys (which are hash-only).

### Security policy enforced in settings

`OAUTH2_PROVIDER` adopts DOT's RFC 9700 (OAuth 2.0 Security BCP) gates
early -- they all default to off in DOT 3.x and flip in 4.0. Enabled:
implicit and password grants rejected, PKCE `plain` rejected (S256
only), access tokens rejected in query strings, and RFC 9207 `iss` in
the authorization response (mix-up defence). The config-validation gates
are on too, so a regression on PKCE, refresh-token reuse protection, or
wildcard redirect URIs fails `manage.py check --deploy`.

Two gates stay off, both documented in
[`app/config/settings.py`](../app/config/settings.py):
`COMPLIANT_BCP_RFC9700_REDIRECT_URI_SCHEME` (it would forbid the
`http://127.0.0.1` loopback callback RFC 8252 native apps need) and
`COMPLIANT_BCP_RFC9700_TOKEN_STORAGE` (the grace-period trade-off
above).

The grant-type policy is enforced in three places that must agree: the
per-app `authorization_grant_type`, the RFC 9700 gates, and the
discovery document. A discovery document that advertises flows the
server rejects sends clients down paths that will fail.

### Implementation

| Piece | Location |
|-------|----------|
| Swapped DOT models | `app/credentials/models.py` (`Application`, `AccessToken`, `RefreshToken`, `Grant`, `IDToken`) |
| DRF authentication | `app/credentials/authentication.py` (`OAuth2Authentication`) |
| Endpoints | `app/credentials/urls.py` |
| Consent + login views | `app/credentials/views.py` |
| Templates | `app/templates/oauth2_provider/authorize.html`, `app/templates/credentials/oauth2_login.html` |
| Expired-token cleanup | `app/credentials/tasks.py` (`clear_expired_oauth2_tokens`, nightly) |

NOTE: DOT does not check `user.is_active` -- it validates the token and
returns its user regardless. `credentials.authentication.OAuth2Authentication`
subclasses DOT's to add that check, so deactivating an account kills its
outstanding grants like it kills every other credential.
