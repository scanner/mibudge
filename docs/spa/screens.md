# Screens

What each screen of the SPA shows and does, and the conventions every
screen shares. [styling.md](styling.md) covers how things look;
[architecture.md](architecture.md) covers where code goes. Each section
names the view (`src/views/`) and the feature code behind it, so you can
go from a screen to its source.

---

## App shell and navigation

`features/shell/AppShell.vue` wraps every signed-in screen.

- **Phones (below `md`):** the TopBar at the top, the page, and the
  BottomNav at the bottom.
- **Tablets and desktops (from `md`):** the SideNav on the left (icons;
  icons and labels from `lg`), with the TopBar and the page beside it.

**TopBar** (`components/layout/TopBar.vue`) has three zones:

- **Left:** a back button on screens below a tab's root.
- **Centre:** the active bank account -- its name and available balance,
  and below them its Unallocated amount. Tapping it opens the account
  switcher.
- **Right:** an action the screen supplies (create budget, search,
  toggle transfers, edit).

**Tabs** (BottomNav and SideNav): Overview (`/app/`), Budgets
(`/app/budgets/`), Transactions (`/app/transactions/`), Account
(`/app/account/`).

**Account switcher** (`components/shared/AccountSwitcher.vue`): a sheet
listing the user's bank accounts with their balances; the active one is
checked. Choosing one makes it the active account, and every screen
scoped to an account reloads for it. "Manage accounts" opens the
Account tab.

## Sign-in and public screens

- **Sign in** (`/app/login/`, `LoginView`, `features/auth/useLogin.ts`):
  email and password; "Forgot password?" goes to the password-reset
  flow. On success the user lands on the page named in `?next=`, or the
  Overview.
- **Email change confirmed / revoked / error**
  (`/app/email-change/...`): the result of following a verification or
  "this wasn't me" link from an email. Public, since the user arrives
  from their mail client.
- **Not found**: any `/app/` path no route matches, with a link to the
  Overview.

## Overview

`/app/`, `OverviewView`, `features/overview/useOverview.ts`.

- The active account's posted, available and free (Unallocated)
  balances.
- A "funded automatically" notice when the account has a funding event
  due.
- The first budgets with their progress and status, and a recurring
  budget's fill-up band. "See all" opens Budgets.
- Recent transactions. "See all" opens Transactions.

## Budgets

**List** (`/app/budgets/`, `BudgetsView`,
`features/budgets/useBudgetList.ts`):

- Tabs: All, Recurring, Capped, Goals, Paused. "All" groups the budgets
  into Recurring, Capped and Goals sections, each sorted by name.
- Each `BudgetCard` shows the name, balance, target, progress, schedule
  and status. A recurring budget with a fill-up goal carries the goal's
  `FillUpBand` inside its card; fill-up goals never appear as budgets of
  their own. The Unallocated budget is not listed (its balance is in the
  TopBar).
- The TopBar offers search and "create budget".

**Detail** (`/app/budgets/:id/`, `BudgetDetailView`,
`features/budgets/useBudgetDetail.ts`):

1. The hero: name, type, balance against the target, progress, status
   and the next funding event, with the fill-up band.
2. "Move money": a sheet (`MoveMoneySheet`) that transfers between this
   budget (or its fill-up goal) and another budget of the account.
3. Configuration: the type's settings (target, cap, amount per event,
   funding schedule, refresh cycle, next fill-up deposit). "Edit" in the
   TopBar opens the full-screen edit sheet (`BudgetEditSheet`); the bank
   account and the budget type cannot change.
4. Pause / resume and Archive; archiving asks for confirmation.
5. The budget's transactions, grouped by date, with search, a toggle to
   include transfers, and a per-row "remove from this budget".

**Create** (`/app/budgets/create/`, `BudgetCreateView` + `BudgetForm`):
choose the type (Goal, Recurring, Capped), then its fields. A recurring
budget can have a fill-up goal, which the backend creates. The
`SchedulePicker` edits a funding schedule or refresh cycle: weekly,
monthly or yearly, with the days, and a plain-English preview.

## Transactions

**List** (`/app/transactions/`, `TransactionsView`,
`features/transactions/useTransactionList.ts`):

- Filter chips: All, Unallocated, Pending, Income.
- Rows are grouped by date under sticky headers, newest first, and the
  next page loads as the list scrolls (`useInfiniteList`).
- A `TransactionRow` shows the party, amount, running balance, type and
  its allocation: one budget with that budget's new balance, a split, or
  "Unallocated". A pending transaction is marked PENDING; a transaction
  still to assign has the unallocated left rule.
- The TopBar toggles transfers between budgets and opens search
  (Cmd/Ctrl-F), which matches loaded rows and asks the server for older
  ones.

**Detail** (`/app/transactions/:id/`, `TransactionDetailView`,
`features/transactions/useTransactionDetail.ts`):

- The hero: party, amount, date and time, account, and PENDING.
- Details: the editable description, the raw description, the type, and
  the account balance after it.
- Allocations: each budget share with its amount and category; "Add
  split" opens the split editor (`SplitEditorDialog`), which shows what
  is left to allocate and assigns any remainder to Unallocated. A
  pending transaction's allocations cannot change until it posts.
- A memo (saved as you type) and attachments.
- ArrowUp / ArrowDown step to the previous / next transaction of the
  list. Transactions are imported; they cannot be created or deleted.

## Account

**Hub** (`/app/account/`, `AccountView`,
`features/settings/useAccountHub.ts`): the profile card (opens Profile);
the bank accounts with posted, available and unallocated balances and
the next funding event ("Add bank account" at the end); settings: the
default account, Security & Notifications, and Sign out.

**Profile** (`/app/account/profile/`, `UserProfileView`): name and
timezone; the email address is changed through a verification email to
the new address and a notice to the old one. An account without a
password (created by invitation) is told how to set one first.

**Security & Notifications** (`/app/account/settings/`,
`AccountSettingsView`): change password; API keys (create, shown once;
revoke with confirmation); notification delivery per kind and the email
digest frequency; pending co-owner invitations the user sent, across
accounts.

**Bank account detail** (`/app/account/bank-accounts/:id/`,
`BankAccountDetailView`): balances; details (the account number, masked,
is editable, as is the name); owners and co-owner invitations; a link to
the account's budgets; funding (data freshness, the next event, the
automatic-funding switch, "Run funding now"); Delete account, with
confirmation.

**Create bank account** (`/app/account/bank-accounts/create/`,
`BankAccountCreateView`): type, name, bank, account number, currency and
opening balances. Balances cannot change after creation; an Unallocated
budget is created with the account.

## Conventions every screen follows

- **Loading:** a first load shows `BaseSkeleton` placeholders shaped
  like the content; loading the next page of a long list shows a small
  spinner at its end.
- **Errors:** an inline `BaseBanner`, never a browser alert; a field's
  error sits under the field.
- **Empty lists:** `EmptyState`, with an action where there is one to
  take.
- **Long lists:** paginated by the API and loaded as you scroll.
- **Unallocated:** the Unallocated budget is never listed as a budget or
  offered as a split target (its balance is in the TopBar). Move money
  offers it, and defaults to it, as the other side of a transfer.
- **Changes that save immediately** (toggles, preferences) show the new
  value at once and fall back to the saved value if the server refuses.
- **Confirmation:** an action that cannot be undone (deleting a bank
  account, archiving a budget, revoking an API key, sending a co-owner
  invitation) asks first in a `ConfirmSheet`. One that is easily redone
  (removing a transaction from a budget, removing a split, cancelling an
  invitation) acts at once.

## Planned layouts

The screens are single-column at every width; wider screens only
swap the BottomNav for the SideNav and show sheets as centred cards.
Planned for tablets and desktops:

- Budgets in two columns, and a budget's detail beside the list on
  desktop.
- Transactions as a list with the selected transaction's detail beside
  it.
- The account switcher as a menu from the TopBar or SideNav.
- Two-column budget and bank-account forms.
