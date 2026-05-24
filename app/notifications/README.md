# Notifications

The `notifications/` Django app is a general-purpose user notification
service.  Its core purpose is to notify users and to let users control
what they receive.  It is designed to be consumed by multiple apps and
services, not to impose any particular user-facing presentation.

`notifications/` is a pluggable Django app.  That contract means it
does not tie itself to any of the apps that consume it -- each consumer
owns its own kind constants and registers them at startup.

---

## Design philosophy

**This service notifies users.  Consumers decide everything else.**

Two distinct APIs serve two distinct concerns:

- **REST API** -- preference management.  Users read and write what
  they want to receive (`/api/v1/notification-preferences/`) and how
  often to receive it (`/api/v1/channel-preferences/`).  Any caller
  with HTTP access can use this -- a browser SPA, a mobile app, an
  external service, or a CLI tool.  The service returns structured data;
  it is up to the calling application to decide how to present that data
  to the user.

- **Python API** (`notify()` / `notify_for()`) -- notification sending.
  In-process Django apps use this to trigger delivery.  Each sending app
  owns its notification kind constants and, for the bundled email channel,
  its own email templates.  Owning templates is appropriate here because
  the sender knows what its notifications need to say.

The key rule: the notification service handles delivery, queuing,
preference enforcement, and channel dispatch.  It does not dictate how
notifications look to the end user, and it does not dictate how
preference controls are presented.  A SPA might show a toggle list; a
CLI tool might use a config flag; a mobile app might use system
notification settings.  The service is agnostic to all of these.

**Channels** are the delivery mechanisms.  The service is designed to
support any combination of: email (implemented), in-app notification
bell, push (APNs / FCM), Slack, and arbitrary webhook integrations.
Adding a new channel means implementing a `BaseChannel` subclass --
the registry, kind strings, and the `notify()` / `notify_for()` API
are unchanged.  Similarly, adding a REST send endpoint (for callers who
want to trigger notifications over HTTP rather than via the Python API)
would not change any existing contracts.

**Access control and scope.**  The service is scoped to users with
accounts.  "User" always means an authenticated account in the system,
never a bare email address or anonymous identity.  Every preference
read and write is tied to `request.user`; a user can only see and
modify their own preferences, and anonymous access is rejected.  This
boundary is also what prevents the service from being used as a channel
for unsolicited messages: if there is no account, the service has
nothing to address.  Any need to send transactional email to an address
that is not yet a user account (invitations, pre-login password resets,
contact replies) belongs in a direct call to the email provider, outside
this service.

---

## 1. Quick-start: adding a new notification kind

This section walks through the five steps needed to add a new kind in
under five minutes.  The example app is `myapp` and the kind is
`myapp.something_happened`.

### Step 1 -- declare the kind constant

Create `myapp/notification_kinds.py`:

```python
from notifications.models import NotificationPriority
from notifications.registry import registry

SOMETHING_HAPPENED = "myapp.something_happened"


def register_all() -> None:
    """Register all myapp notification kinds. Called from MyAppConfig.ready()."""
    registry.register(
        kind=SOMETHING_HAPPENED,
        display_name="Something happened",
        default_priority=NotificationPriority.NORMAL,
        can_suppress=True,
        default_opt_in=True,
        recipients=lambda obj: obj.members.all(),  # fan-out target for notify_for()
    )
```

The `recipients` callable is only needed when you intend to call
`notify_for()`.  For kinds that are always fired per-user with
`notify()` directly, omit it.

### Step 2 -- register from AppConfig.ready()

In `myapp/apps.py`:

```python
from django.apps import AppConfig


class MyAppConfig(AppConfig):
    name = "myapp"

    def ready(self) -> None:
        # Deferred import: notification_kinds imports from notifications.models,
        # which requires the app registry to be fully initialized.
        from . import notification_kinds
        notification_kinds.register_all()
```

The deferred import inside `ready()` is mandatory -- importing at
module level would touch Django models before the app registry is
ready.

### Step 3 -- add templates

Create the template directory and three files:

```
templates/notifications/myapp/something_happened/
    email_subject.en-us.txt
    email_body.en-us.txt
    email_body.en-us.html
```

`email_subject.en-us.txt` -- one line, no trailing newline:
```
Something happened in your account
```

`email_body.en-us.txt`:
```
Hello {{ user.name }},

Something happened in your account on {{ date }}.
```

`email_body.en-us.html`:
```html
<p>Hello {{ user.name }},</p>
<p>Something happened in your account on {{ date }}.</p>
```

The context dict you pass to `notify()` becomes the template context.
A `notification` key (the `Notification` model instance) is injected
automatically.

### Step 4 -- fire the notification

Per-user:

```python
from myapp.notification_kinds import SOMETHING_HAPPENED
from notifications.service import notify

def handle_something(user, date):
    notify(user, SOMETHING_HAPPENED, {"date": date})
```

Fan-out via the registered `recipients` callable:

```python
from notifications.service import notify_for

notify_for(obj, SOMETHING_HAPPENED, {"date": date})
```

`notify_for()` calls the `recipients` callable you registered with the
kind, iterates the returned users, and calls `notify()` for each one.

### Step 5 -- verify

Run the test suite to confirm lint and type-check pass:

```bash
make lint
uv run pytest app/tests/notifications/ -v
```

---

## 2. Usage reference

### `notify()`

```python
from notifications.service import notify

notify(
    user,          # User instance (recipient)
    kind,          # Dotted kind string, e.g. "myapp.something_happened"
    context,       # dict -- rendered into templates
    priority=None, # Optional[int] -- NotificationPriority constant; defaults to kind's registry value
    locale=None,   # Optional[str] -- BCP 47 tag, e.g. "fr-ca"; defaults to NOTIFICATIONS_DEFAULT_LOCALE
) -> Notification | None
```

Returns the created `Notification` instance, or `None` if the user
has opted out of the kind.

Raises `ValueError` if `kind` is not registered.

**CRITICAL priority** bypasses the digest queue: a Celery task is
enqueued immediately to send a standalone email.  All other priorities
land in the pending queue and are dispatched by the `flush_email_digests`
periodic task.

**Opt-out behaviour**: if `can_suppress` is `True` for the kind *and*
the user's `NotificationPreference` row (or the kind's `default_opt_in`
default) is `False`, `notify()` returns `None` without creating a row.
Kinds with `can_suppress=False` are always delivered regardless of
preferences (CRITICAL / security notifications).

### `notify_for()`

```python
from notifications.service import notify_for

notify_for(
    obj,           # any domain object -- passed to the kind's recipients callable
    kind,          # str
    context,       # dict
    priority=None, # Optional[int]
) -> list[Notification]
```

Looks up the `recipients` callable registered with the kind, passes
`obj` to it, and calls `notify()` for each returned user.  Each
recipient uses their own preferences and locale independently.  Returns
a list of created `Notification` instances (may be shorter than the
recipient count if some have opted out).

Raises `ValueError` if the kind is not registered or has no
`recipients` callable.

### Kind registration API

```python
from notifications.registry import registry
from notifications.models import NotificationPriority

registry.register(
    kind,              # str -- globally unique dotted string, e.g. "myapp.thing"
    display_name,      # str -- shown in the preferences UI
    default_priority,  # int -- NotificationPriority constant
    can_suppress=True,    # bool -- whether users can opt out
    default_opt_in=True,  # bool -- whether new users receive this by default
    recipients=None,      # Callable[[Any], Iterable[User]] | None -- for notify_for()
)
```

Raises `ValueError` if `kind` is already registered.

`registry.get(kind)` returns a `KindInfo` dataclass or `None`.
`registry.all()` returns all registered kinds sorted by kind string.

**`can_suppress` vs `default_opt_in`**:

| `can_suppress` | `default_opt_in` | Effect |
|---|---|---|
| `False` | `True` | Always delivered; not shown in preferences UI |
| `True` | `True` | Delivered by default; user can opt out |
| `True` | `False` | Not delivered by default; user can opt in |

### Priority levels

| Level | Value | Can suppress? | Delivery |
|---|---|---|---|
| `CRITICAL` | 1 | No | Immediate (standalone email, Celery task) |
| `HIGH` | 2 | No | Digest queue |
| `NORMAL` | 3 | Yes | Digest queue |
| `LOW` | 4 | Yes | Digest queue |

### Template convention

Templates live under `templates/notifications/<app>/<kind>/` where
`<app>` and `<kind>` come from splitting the dotted kind string on the
**first** dot:

```
templates/notifications/
    <app>/
        <kind>/
            email_subject.<locale>.txt    # one-line subject
            email_body.<locale>.txt       # plain-text body
            email_body.<locale>.html      # HTML body
    email_digest_subject.<locale>.txt     # shared digest subject
    email_digest_body.<locale>.txt        # shared digest plain-text
    email_digest_body.<locale>.html       # shared digest HTML
```

Locale tags follow BCP 47 with a hyphen, lower-cased -- e.g. `en-us`,
`fr-ca`, `zh-hans`.  Adding a new language means adding template files;
no code changes are needed.

**Locale fallback**: if the user's locale template is absent, the
loader tries `NOTIFICATIONS_DEFAULT_LOCALE` next.  If neither exists,
`TemplateDoesNotExist` is raised and the `NotificationLog` row is
marked `FAILED`.

**CRITICAL standalone sends** use the kind-specific templates directly.

**Digest sends** use the shared `email_digest_*` wrapper templates.
Each notification in the batch is pre-rendered and passed to the
wrapper as `items` -- a list of dicts with keys `notification`,
`text_body`, and `html_body`.  The wrapper assembles them into one
email.

**Context variables available in all kind templates**:

| Variable                             | Type           | Description                                 |
|--------------------------------------|----------------|---------------------------------------------|
| `notification`                       | `Notification` | The model instance (injected automatically) |
| *(all keys from the `context` dict)* | any            | Caller-supplied context                     |

**Built-in kind context variables**:

| Kind                          | Variables                                                                               |
|-------------------------------|-----------------------------------------------------------------------------------------|
| `moneypools.funding_complete` | `account_name`, `transfers` (int), `warnings` (list[str]), `date` (ISO string)          |
| `moneypools.import_complete`  | `account_name`, `new_count` (int), `pending_to_posted_count` (int), `date` (ISO string) |
| `users.password_changed`      | `changed_at` (datetime string)                                                          |

**Digest wrapper context variables**:

| Variable     | Type         | Description                                  |
|--------------|--------------|----------------------------------------------|
| `user`       | `User`       | The recipient                                |
| `items`      | `list[dict]` | Per-notification rendered bodies (see above) |
| `item_count` | `int`        | Length of `items`                            |

### Digest frequencies

Users configure how often they receive digest emails via
`ChannelPreference.digest_frequency`:

| Value             | Label                         | Delivery time                 |
|-------------------|-------------------------------|-------------------------------|
| `daily_morning`   | Once daily (morning)          | ~7 am local time              |
| `daily_evening`   | Once daily (evening, default) | ~6 pm local time              |
| `twice_daily`     | Twice daily                   | ~7 am + ~6 pm local time      |
| `weekly_friday`   | Weekly on Friday              | ~7 am local time on Fridays   |
| `weekly_saturday` | Weekly on Saturday            | ~7 am local time on Saturdays |
| `weekly_sunday`   | Weekly on Sunday              | ~7 am local time on Sundays   |

"Local time" uses the `timezone` field on the `User` model (an IANA
timezone name, e.g. `America/Los_Angeles`).  Invalid or missing
timezones fall back to UTC.

---

## 3. Configuration reference

### Settings (`app/config/settings.py`)

| Setting                        | Default         | Description                                                                                                                                                   |
|--------------------------------|-----------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `NOTIFICATIONS_DEFAULT_LOCALE` | `LANGUAGE_CODE` | BCP 47 locale used when no locale is supplied to `notify()` and as the final fallback in the template loader. Set via `NOTIFICATIONS_DEFAULT_LOCALE` env var. |
| `NOTIFICATIONS_RETENTION_DAYS` | `90`            | Notification and log rows older than this many days are deleted by the `purge_old_notifications` task. Set via `NOTIFICATIONS_RETENTION_DAYS` env var.        |

### Celery periodic tasks

Both tasks are registered in `MANAGED_PERIODIC_TASKS` in
`app/config/celery_app.py` and are created/updated automatically when
Celery Beat starts.  To override a schedule, create an admin-managed
task with a different name (no `[managed] ` prefix) -- the managed
entry can then be disabled via the admin.

| Task                    | Dotted path                                   | Schedule                             |
|-------------------------|-----------------------------------------------|--------------------------------------|
| Flush email digests     | `notifications.tasks.flush_email_digests`     | Every 30 min (`0,30` past each hour) |
| Purge old notifications | `notifications.tasks.purge_old_notifications` | Daily at 3:00 AM UTC                 |

---

## 4. Architecture and design notes

### Why free-form kind strings instead of a central enum

Enums require a single import point that every app must depend on.
Free-form dotted strings let each consuming app own its kind constants
in a local `notification_kinds.py` module -- consistent with
`notifications/` being a pluggable app.  The registry is the only
shared contract, and it is owned by `notifications/`.

### `Notification` vs `NotificationLog`

`Notification` is the pending queue.  One row per event, per user.
`log_entry` is `NULL` while the notification is waiting.

`NotificationLog` is the dispatch record.  One row per send event -- a
standalone CRITICAL email or a digest batch.  A single log row may
cover many `Notification` rows (digest).  When the channel layer sends
successfully, it sets `log_entry` on every dispatched `Notification`
row, linking them to the log entry.  A log row with `status=FAILED`
records the error in `error_detail`.

```
Notification (pending)        NotificationLog
  log_entry = NULL    ─────┐
  log_entry = NULL    ──── │ (digest flush)
  log_entry = NULL    ─────┘  → NotificationLog (status=SENT)
                               → Notification.log_entry set for all three
```

### Digest flush mechanics

`flush_email_digests` runs every 30 minutes.  For each user with
pending email notifications it:

1. Fetches or creates a `ChannelPreference` row.
2. Calls `_is_digest_due(user, pref, now_utc)` to check the delivery
   window.
3. If due, fetches all pending notifications for that user and calls
   `EmailChannel.send_batch()`.
4. Updates `ChannelPreference.last_digest_sent_at` to the current UTC
   time to prevent double-sending within the same 30-minute window.

`_is_digest_due()` uses `match/case` with guard conditions to check
whether the current local hour (and weekday, for weekly frequencies)
matches the configured `DigestFrequency`.  It returns `False` if we are
outside the window *or* if `last_digest_sent_at` falls within the same
local date+hour as now.

The function is typed via `Protocol` (`_HasTimezone`, `_HasDigestPref`)
rather than concrete model types, so tests can pass lightweight
`SimpleNamespace` objects without DB access.

### `notify_for()` and the recipients callable

As a pluggable app, `notifications/` cannot depend on its consumers.
Rather than `notify_for()` knowing how to resolve recipients from any
given domain object, that knowledge lives in the kind registration
itself: each consumer passes a `recipients` callable when registering
its kinds.  `notify_for()` is therefore entirely generic — it receives
a domain object, calls the registered callable to get an iterable of
users, and fans out via `notify()`.

The `recipients` callable is defined in the consuming app's
`notification_kinds.py` alongside the kind constants it serves.  For
example, `moneypools` registers `recipients=lambda account:
account.owners.all()` for all its account-level kinds.  The type
annotation on `notify_for()`'s `obj` parameter is `Any` rather than a
concrete model type — consistent with `notifications/` being a
pluggable app.

### BCP 47 locale choice

Django's `LANGUAGE_CODE` uses BCP 47 tags with hyphens (e.g. `en-us`,
`zh-hans`).  The notification service follows this convention so locale
values flow through settings and the template loader without conversion.
Note: some internal docstrings in `channels/email.py` use the older
`en_US` (underscore) form -- these are stale and the actual template
filenames use `en-us` (hyphen).

### `can_suppress` / `default_opt_in` distinction

Both flags exist because they control independent axes:

- **`can_suppress`** controls *whether* the user has any say.  Setting
  this to `False` removes the preference from the UI and bypasses the
  preference gate in `notify()`.  Use it for security and compliance
  notifications where delivery is mandatory.
- **`default_opt_in`** controls the *starting state* for a suppressible
  kind.  A `LOW` priority import-complete notification has
  `default_opt_in=False` because most users do not want it; a user who
  does can opt in.  A `NORMAL` priority funding-complete notification
  has `default_opt_in=True` because it is useful by default.

---

## 5. Future directions

The following are not implemented but the architecture is designed to
accommodate them without breaking changes.

**Push channel (APNs / FCM)**: add a `PushChannel(BaseChannel)`
subclass, a device-token model, and a `Channel.PUSH` branch in the
service and tasks.  The registry, kind strings, and `notify()` API are
unchanged.

**Per-user locale**: add a `locale` field to the `User` model and
thread it through `notify()` instead of always reading from settings.
The template loader already handles arbitrary BCP 47 tags.

**In-app notification bell**: expose pending/unread `Notification` rows
via a REST endpoint.  Add a `read_at` timestamp to `Notification` and
an unread-count endpoint; the existing queue model requires no schema
change for the unread-count case.

**Webhook channel for integrations**: a `WebhookChannel` that POSTs
the notification context JSON to a user-configured URL.

**Digest preview endpoint**: render what the next digest would look
like for a given user, useful for testing templates in a development
environment.
