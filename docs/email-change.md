# Self-service email change

Users can change the email address they log in with via
`POST /api/v1/users/me/change-email/`. Because the email address *is*
the account identity -- it is the username, the login credential, and
the password-reset channel -- changing it is the single most dangerous
self-service operation in mibudge. This document explains the flow and
the reasoning behind each protection.

The service layer is
[`app/users/email_change.py`](../app/users/email_change.py); the
`EmailChangeRequest` model is in
[`app/users/models.py`](../app/users/models.py).

---

## Threat model

The design assumes an attacker who has **temporarily hijacked an
authenticated session** (stolen device, XSS, walked-up-to-an-unlocked
laptop) but does not control the user's mailbox. Such an attacker's
goal is to rotate the account's email to an address they control: once
that sticks, they own the password-reset channel and therefore the
account, permanently.

The counter-design: every change must be *verified* by the new address,
*announced* to the old address, and *reversible* by the old address for
long enough that the legitimate owner will plausibly notice -- even if
they were on vacation when it happened.

## The flow

```
 request ──► verification email to NEW address  (confirm link, 24 h)
         └─► notification email to OLD address  (revoke link)

 confirm ──► User.email/username updated
         └─► 7-day revocation window opens

 revoke  ──► (post-confirm) email reverted, all sessions invalidated,
             security alerts to BOTH addresses
```

1. **Request** (`create_request()`): the authenticated user submits
   `new_email`. Two emails go out immediately: a verification link to
   the new address, and a "this change was requested -- click here if
   this wasn't you" notification with a **revoke link** to the old
   address.
2. **Confirm** (`confirm_request()`): the new-address recipient clicks
   the verification link within `EMAIL_CHANGE_TOKEN_EXPIRY_HOURS`
   (24 h). The user's `email` and `username` are updated and the
   revocation window opens.
3. **Revoke** (`revoke_request()`): at any point before confirmation,
   or up to `EMAIL_CHANGE_REVOCATION_DAYS` (7 days) after it, the
   revoke link cancels the change. Post-confirmation revocation
   reverts `email`/`username` to the old address, **invalidates every
   active session**, and sends security alerts to both addresses.

The key property: **the revoke link stays valid for 7 days *after* an
attacker confirms the change**. Rotating the email does not lock the
legitimate owner out of undoing it -- the old inbox retains veto power
for the whole window.

## Protections and their reasons

### Usable password required (403)

`change_email` in
[`app/users/api/v1/views.py`](../app/users/api/v1/views.py) refuses if
`has_usable_password()` is false. Accounts created via the invitation
flows start passwordless (see [`invitations.md`](invitations.md));
requiring a password first ensures there is always a second credential
anchoring the account before its primary identifier can move. The same
gate applies to `change-password`.

### Interactive sessions only

The initiating endpoint carries `RequiresInteractiveAuth`
([`app/users/permissions.py`](../app/users/permissions.py)): a leaked
API key can read budgets, but it can never rotate the account's email.
See [`authentication.md`](authentication.md).

### One change at a time (409)

`create_request()` refuses while a previously confirmed change is
still inside its revocation window (`RevocationWindowOpenError`).
Without this lockout an attacker could chain changes --
`victim@ → attacker1@ → attacker2@` -- so that by the time the victim
clicks their revoke link it only undoes the *last* hop, or the earlier
window has been buried. The lockout guarantees at most one change is
ever in flight, and the old address's revoke link covers it fully.

### Revocation is deliberately more forgiving than confirmation

`EmailChangeRequest.is_revocable`
([`app/users/models.py`](../app/users/models.py)): before confirmation
the revoke link works **even after the 24-hour verification token has
expired** -- token expiry should stop the change from being applied,
never stop the owner from cancelling it. After confirmation it works
until `revocable_until`.

### Session invalidation on revocation

Post-confirmation revocation blacklists every outstanding JWT refresh
token for the user (`_invalidate_all_sessions()` in
[`app/users/email_change.py`](../app/users/email_change.py)). The
attacker's hijacked session dies as soon as its short-lived access
token expires (≤ 60 minutes) and cannot be refreshed. Alerts go to
*both* addresses -- the old one so the owner knows the revert
succeeded, the new one because a real person may sit behind it (e.g.
a typo'd address) and should know their address was involved.

### Uniqueness checked twice

The `new_email` is checked against existing accounts at request time
*and again* at confirm time (`confirm_request()`), because another
account could have claimed the address during the 24-hour gap.

### Audit trail

`EmailChangeRequest` rows are never deleted; every request, confirm,
and revoke timestamp is preserved.

### Locale pinned to the requesting user

All emails in the flow render in the *requesting user's* locale, never
a preference the (possibly attacker-controlled) session set on the fly
-- otherwise an attacker could switch the account language before
attacking so the security notifications arrive in a language the owner
cannot read (the "language-lock" attack). See the notes on
`_send_verification_email()` in
[`app/users/email_change.py`](../app/users/email_change.py).

## Dual-path design: browser links and native apps

The links embedded in the emails point at Django GET views
(`/users/email-change/{token}/confirm/` and `.../revoke/`, in
[`app/users/views.py`](../app/users/views.py)), which process the
action and redirect the browser to an SPA result page
(`/app/email-change/confirmed/`, `.../revoked/`, or `.../error/` with a
`reason` query param).

Native mobile apps can register the production domain as a Universal
Link (iOS) / App Link (Android); the OS then opens the app instead of
a browser, and the app extracts the token and calls the equivalent
REST endpoints. Both paths call the same service functions in
[`app/users/email_change.py`](../app/users/email_change.py), so the
business logic lives in exactly one place.

| Endpoint                                              | Auth        | Action                          |
|--------------------------------------------------------|-------------|----------------------------------|
| `POST /api/v1/users/me/change-email/`                  | JWT (interactive) | Initiate a change          |
| `POST /api/v1/users/me/change-email/{token}/confirm/`  | None (token is the credential) | Confirm     |
| `POST /api/v1/users/me/change-email/{token}/revoke/`   | None (token is the credential) | Revoke      |
| `GET /users/email-change/{token}/confirm/`             | None        | Browser confirm link → SPA redirect |
| `GET /users/email-change/{token}/revoke/`              | None        | Browser revoke link → SPA redirect  |

Tokens are 64-character URL-safe secrets from
[`app/common/tokens.py`](../app/common/tokens.py) (384 bits of
entropy) -- the same token-is-the-credential design as
[invitations](invitations.md).

## Settings

Defined in [`app/config/settings.py`](../app/config/settings.py):

| Setting                           | Default | Meaning                                              |
|-----------------------------------|---------|-------------------------------------------------------|
| `EMAIL_CHANGE_TOKEN_EXPIRY_HOURS` | 24      | How long the new-address verification link is valid  |
| `EMAIL_CHANGE_REVOCATION_DAYS`    | 7       | How long after confirmation the revoke link is valid  |

## Implementation map

| Piece                       | Location                                                     |
|-----------------------------|---------------------------------------------------------------|
| Service layer (all business logic) | [`app/users/email_change.py`](../app/users/email_change.py) |
| `EmailChangeRequest` model  | [`app/users/models.py`](../app/users/models.py)              |
| REST endpoints              | [`app/users/api/v1/views.py`](../app/users/api/v1/views.py) (`UserViewSet.change_email*`) |
| Browser link views          | [`app/users/views.py`](../app/users/views.py)                |
| URL registration            | [`app/users/urls.py`](../app/users/urls.py)                  |
| Old-address notifications   | `EMAIL_CHANGE_REQUESTED` / `EMAIL_CHANGE_SECURITY_ALERT` in [`app/users/notification_kinds.py`](../app/users/notification_kinds.py) |
| Settings knobs              | [`app/config/settings.py`](../app/config/settings.py)        |
