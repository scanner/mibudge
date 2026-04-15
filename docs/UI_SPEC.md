# MiBudge — UI Specification
> Reference document for Claude Code. Describes the complete frontend design system,
> component library, screen inventory, routing, API mapping, and known gaps requiring
> backend extension. Implement this as a Vue 3 SPA.

---

## 1. Stack & Project Layout

| Concern      | Choice                                                   |
|--------------|----------------------------------------------------------|
| Framework    | Vue 3 (Composition API + `<script setup>`)               |
| Build        | Vite + `django-vite` (HMR in dev, staticfiles in prod)   |
| Language     | TypeScript throughout — no `any` unless unavoidable      |
| State        | Pinia                                                    |
| Router       | Vue Router 4, history mode, base `/app/`                 |
| HTTP         | Native `fetch` wrapper at `src/api/client.ts` — no Axios |
| Icons        | Tabler Icons (`@tabler/icons-vue`)                       |
| CSS          | Tailwind CSS v3                                          |
| Fonts        | IBM Plex Sans + IBM Plex Mono (Google Fonts)             |
| Build output | `frontend/dist/` collected by Django staticfiles         |

### Directory skeleton

```
frontend/
  src/
    api/
      client.ts          # fetch wrapper, JWT attach, token refresh
      bankAccounts.ts
      budgets.ts
      transactions.ts
      allocations.ts
      internalTransactions.ts
      banks.ts
      users.ts
    components/
      layout/
        AppShell.vue       # persistent header + bottom nav (mobile) / sidebar (≥md)
        TopBar.vue         # unallocated amount + account context pill
        BottomNav.vue
        SideNav.vue
      budgets/
        BudgetCard.vue
        FillUpBand.vue
        BudgetDetailHero.vue
        BudgetForm.vue
        SchedulePicker.vue
      transactions/
        TransactionRow.vue
        TransactionDetail.vue
        AllocationCard.vue
        SplitPopup.vue
      accounts/
        AccountRow.vue
        AccountDetail.vue
        AccountForm.vue
      shared/
        ProgressBar.vue
        StatusChip.vue
        MoneyAmount.vue    # formats decimal + currency, applies IBM Plex Mono
        ConfirmSheet.vue   # bottom sheet for destructive confirmations
        EmptyState.vue
    stores/
      auth.ts
      accountContext.ts   # active bank account + unallocated budget UUID
      budgets.ts
      transactions.ts
      banks.ts
    views/
      LoginView.vue
      BudgetsView.vue
      BudgetDetailView.vue
      TransactionsView.vue
      TransactionDetailView.vue
      AccountView.vue
      BankAccountDetailView.vue
    router/
      index.ts
    types/
      api.ts              # TypeScript interfaces mirroring API schemas
    main.ts
```

---

## 2. Design System

### 2.1 Typography

```css
/* Load via Google Fonts */
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500&family=IBM+Plex+Mono:wght@400;500&display=swap');

font-family: 'IBM Plex Sans', system-ui, sans-serif;  /* body */
font-family: 'IBM Plex Mono', monospace;               /* all monetary amounts */
```

IBM Plex Sans has a slashed zero by default — zero/O disambiguation is built in.
IBM Plex Mono is used for **every monetary amount** rendered in the UI.

| Role                       | Size    | Weight | Notes                           |
|----------------------------|---------|--------|---------------------------------|
| Hero amount (balance)      | 36px    | 500    | Mono                            |
| Section header amount      | 22px    | 500    | Mono                            |
| Card balance               | 15px    | 500    | Mono                            |
| Card target / meta amounts | 11–13px | 400    | Mono                            |
| Page title                 | 22px    | 500    | Sans                            |
| Nav title                  | 16px    | 500    | Sans                            |
| List item title            | 15px    | 500    | Sans                            |
| List item meta             | 11–12px | 400    | Sans, muted                     |
| Section label              | 11px    | 600    | Sans, uppercase, 0.06em spacing |
| Body / field label         | 13–14px | 400    | Sans                            |

### 2.2 Colour Palette

All colours as Tailwind custom tokens in `tailwind.config.ts`:

```ts
colors: {
  ocean: {
    50:  '#EAF4FF',
    400: '#378ADD',
    600: '#185FA5',
    800: '#0C447C',
  },
  mint: {
    50:  '#E1F5EE',
    400: '#1D9E75',
    600: '#0F6E56',
    800: '#085041',
  },
  amber: {
    50:  '#FFF5E6',
    400: '#EF9F27',
    600: '#854F0B',
  },
  coral: {
    50:  '#FCEBEB',
    400: '#E24B4A',
    600: '#A32D2D',
  },
  neutral: {
    50:  '#F5F4F0',
    100: '#F1EFE8',
    200: '#E0DED8',
    300: '#D3D1C7',
    400: '#B4B2A9',
    500: '#888780',
    600: '#5F5E5A',
    700: '#444441',
    900: '#1a1a1a',
  },
}
```

**Semantic colour mapping:**

| State                         | Background    | Text / stroke           |
|-------------------------------|---------------|-------------------------|
| Funded / healthy              | `mint-50`     | `mint-600`              |
| In progress                   | `ocean-50`    | `ocean-600`             |
| Needs attention / behind pace | `amber-50`    | `amber-600`             |
| Overspent / danger            | `coral-50`    | `coral-600`             |
| Paused / inactive             | `neutral-100` | `neutral-600`           |
| Unallocated (header label)    | —             | `mint-400`              |
| Account balance (header)      | —             | `neutral-400` (subdued) |

### 2.3 Spacing & Radius

```
Page padding:   16px horizontal
Card radius:    14px (large cards), 10–12px (sub-cards, chips)
Card border:    0.5px solid neutral-200
Section gap:    10–12px between cards
Row divider:    0.5px solid neutral-100 (#F1EFE8)
Progress bar:   5px height (budget cards), 8px (detail hero), 3px (fill-up band)
```

### 2.4 Progress Bar Colours

| Condition           | Fill colour   |
|---------------------|---------------|
| 100%, not overspent | `mint-400`    |
| 1–99%               | `ocean-400`   |
| Behind pace (goal)  | `amber-400`   |
| Overspent           | `coral-400`   |
| Paused              | `neutral-400` |

### 2.5 Status Chips

Reusable `<StatusChip>` component accepts a `status` prop:

```ts
type BudgetStatus = 'funded' | 'progress' | 'warn' | 'over' | 'paused'
```

Renders as a pill with matching `bg` / `text` colour pair from the semantic table above.

### 2.6 Icon Usage (Tabler Icons)

Import named icons from `@tabler/icons-vue`. Common mappings:

| Concept                       | Tabler icon                                           |
|-------------------------------|-------------------------------------------------------|
| Hamburger menu                | `IconMenu2`                                           |
| Add / create                  | `IconPlus`                                            |
| Edit                          | `IconPencil`                                          |
| Delete                        | `IconTrash`                                           |
| Back / chevron left           | `IconChevronLeft`                                     |
| Chevron right (row)           | `IconChevronRight`                                    |
| Chevron down                  | `IconChevronDown`                                     |
| Budget / wallet               | `IconWallet`                                          |
| Recurring                     | `IconRefresh`                                         |
| Goal                          | `IconTarget`                                          |
| Fill-up                       | `IconArrowBarToDown`                                  |
| Transaction                   | `IconList`                                            |
| Bank account                  | `IconBuildingBank`                                    |
| Lock / account number         | `IconLock`                                            |
| Calendar                      | `IconCalendar`                                        |
| Clock / schedule              | `IconClock`                                           |
| Move money                    | `IconArrowsRightLeft`                                 |
| Funding / arrow down into box | `IconArrowBarDown`                                    |
| Search                        | `IconSearch`                                          |
| Pause                         | `IconPlayerPause`                                     |
| Attach photo                  | `IconPhoto`                                           |
| Attach document               | `IconFile`                                            |
| Overview / grid               | `IconLayoutGrid`                                      |
| User / account tab            | `IconUser`                                            |
| Swipe-delete hint             | `IconChevronLeft` + `IconTrash` (inline, 40% opacity) |

---

## 3. Layout & Navigation

### 3.1 Responsive Breakpoints

```
Mobile:   < 768px  — bottom tab bar, single column, slide navigation
Tablet:   768px–1279px — left sidebar (collapsed icons), two-column list+detail
Desktop:  ≥ 1280px — left sidebar (full labels), list+detail split view
```

### 3.2 Persistent Header (`TopBar.vue`)

Present on every authenticated screen. Three zones:

```
[ hamburger / back ]   [ account context ]   [ contextual action ]
```

**Account context centre block** (always visible, tappable):

```
Chase Checking · $6,842.10    ← subdued, 11px, neutral-400, with ChevronDown
        $1,240.38              ← dominant, 22px, 500 weight
        UNALLOCATED            ← 10px, 600 weight, uppercase, mint-400
```

Tapping the centre block opens the **account switcher sheet** — a bottom sheet listing all user bank accounts with their unallocated amounts. Selecting an account sets the global `accountContext` store, which filters all subsequent API calls. The selected account is indicated with a checkmark and its dot colour.

The account switcher sheet also contains "Manage accounts →" which navigates to the Account tab.

**Contextual action (right slot):**
- Budgets list → `IconPlus` (create budget)
- Budget detail → "Edit" text
- Transactions list → `IconSearch`
- Transaction detail → nothing
- Account → nothing

### 3.3 Bottom Tab Bar (mobile) / Side Nav (tablet+)

Four tabs:

| Tab          | Icon             | Route                |
|--------------|------------------|----------------------|
| Overview     | `IconLayoutGrid` | `/app/`              |
| Budgets      | `IconWallet`     | `/app/budgets/`      |
| Transactions | `IconList`       | `/app/transactions/` |
| Account      | `IconUser`       | `/app/account/`      |

Active tab: `ocean-400` icon + label. Inactive: `neutral-500`.

On tablet/desktop the sidebar shows the same four items vertically with labels, plus the account context block at the top.

---

## 4. Screen Inventory & Component Breakdown

### 4.1 Login View (`/app/login/`)

- Username + password fields
- Submit → `POST /api/token/` → store `access` token in memory (Pinia), `refresh` in httpOnly cookie
- On success → redirect to `/app/`
- On 401 → inline error message
- No "forgot password" in v1

### 4.2 Budgets View (`/app/budgets/`)

**API:** `GET /api/v1/budgets/?bank_account={uuid}&ordering=name`

**Filter tabs** (maps to query params):

| Tab | Params |
|---|---|
| All | `archived=false` |
| Recurring | `budget_type=R&archived=false` |
| Goals | `budget_type=G&archived=false` |
| Paused | `paused=true&archived=false` |

**List structure:**

Sections: "Recurring" then "Goals" (when tab = All).
Within each section, cards sorted by name.
`ASSOCIATED_FILLUP_GOAL` (`budget_type=A`) budgets are **never shown as standalone rows** — they appear only as the `FillUpBand` component attached to their parent recurring budget card.

**`BudgetCard.vue` props:**

```ts
interface BudgetCardProps {
  budget: Budget
  fillupBudget?: Budget  // present when budget.with_fillup_goal === true
}
```

Card layout:
```
[ Name                    ] [ $balance  ]
[ meta: type · reset date ] [ of $target ]
[====== progress bar ========]
[ $X · schedule            ] [ StatusChip ]
```

When `fillupBudget` is provided, a `FillUpBand` is attached as the bottom section of the same card (same border-radius container, blue-tinted background `#F5FAFF`, `border-top: 0.5px solid #D4E9F7`):

```
[↓ Next cycle saving         $44 of $80 ]
[=== thin progress bar (3px) ============]
[ $20/payday · ready at cycle reset      ]
```

**Unallocated budget:** The unallocated budget UUID comes from `BankAccount.unallocated_budget`. It is **not shown in the budget list**. Its balance is shown in the `TopBar` as the "Unallocated" amount.

**FAB / add button:** `IconPlus` in the top-right of the nav bar → navigates to `/app/budgets/create/`.

### 4.3 Budget Detail View (`/app/budgets/:id/`)

**API:** `GET /api/v1/budgets/:id/`

**Hero block:**

```
[ Budget name        ] [ type chip ]
[ account · date/cycle meta        ]
[ $balance              / $target  ]
[======= progress bar (8px) =======]
[ date start            date end   ]  ← progress bar axis labels
[ StatusChip      Next funding: X  ]
```

For recurring budgets with `with_fillup_goal=true`, a `FillUpBand` is appended inside the hero (same treatment as the list card).

**"Move money" CTA button** — ocean-50 background, ocean-400 icon + text:
```
[ → ]  Move money
       Transfer to or from another budget
```
Tapping opens the internal transaction form (bottom sheet):
- Source budget (pre-filled to this budget, but swappable)
- Destination budget (budget picker — all budgets in same bank account)
- Amount
- Submit → `POST /api/v1/internal-transactions/`

**Configuration section** — tappable rows that navigate to individual edit sub-screens:

For **Goal** budgets:
- Target amount → `PATCH /api/v1/budgets/:id/` `{target_balance}`
- Target date → `PATCH` `{target_date}`
- Funding schedule → `PATCH` `{funding_schedule, funding_type}`

For **Recurring** budgets:
- Refresh cycle → `PATCH` `{recurrence_schedule}`
- Funding schedule → `PATCH` `{funding_schedule, funding_type}`
- Target amount → `PATCH` `{target_balance}`
- Fill-up goal → `PATCH` `{with_fillup_goal}` (toggle on/off)

**Recent transactions section:**
- `GET /api/v1/transactions/?bank_account={uuid}` filtered client-side to those with an allocation pointing at this budget UUID
- Also `GET /api/v1/internal-transactions/?src_budget={uuid}` and `?dst_budget={uuid}` — shown with "· internal" label
- "See all transactions →" navigates to Transactions view pre-filtered to this budget

**Bottom action row:**
- "Pause budget" → `PATCH {paused: true}` (toggle, label changes to "Resume budget" when paused)
- "Delete budget" → confirmation sheet → `DELETE /api/v1/budgets/:id/` (note: unallocated budget returns 403 — handle gracefully, this button should not appear for the unallocated budget)

**Edit flow:** The "Edit" button in the nav bar opens the `BudgetForm` in edit mode. `bank_account` and `budget_type` are immutable after creation — these fields are shown as read-only in edit mode.

### 4.4 Budget Create View (`/app/budgets/create/`)

**API:** `POST /api/v1/budgets/`

**Type selector** — two-button segmented control at top of form:

```
[ 🎯  Goal                ] [ 🔁  Recurring           ]
[ Save toward a target    ] [ Refills on a schedule   ]
```

Selecting a type mutates the form fields shown below it.

**Common fields (both types):**
- Name (text input, required)
- Account (read-only, taken from `accountContext` store, shown as tappable row for clarity)

**Goal-specific fields:**
- Target amount (decimal input, IBM Plex Mono)
- Target date (date picker)
- Funding schedule (see `SchedulePicker` component, section 5.1)
- Funding type toggle: "Auto" (calculate from target + date = `funding_type: 'auto'`) or "Fixed" (flat amount per event = `funding_type: 'fixed'`)
- When "Fixed": additional amount-per-event input appears

**Recurring-specific fields:**
- Target amount (decimal input)
- Refresh cycle (`SchedulePicker` — the `recurrence_schedule` field)
- Funding schedule (`SchedulePicker` — the `funding_schedule` field)
- Fill-up goal toggle (boolean, `with_fillup_goal`) — with sub-label "Saves for the next cycle while this one is active"
- Start paused toggle (`paused`)

**Save button:** Disabled until name is non-empty. On submit maps form state to `BudgetRequest` body.

**`ASSOCIATED_FILLUP_GOAL` budgets** are auto-created by the backend when `with_fillup_goal=true` — the frontend never creates them directly.

### 4.5 Transactions View (`/app/transactions/`)

**API:** `GET /api/v1/transactions/?bank_account={uuid}&ordering=-transaction_date`

**Filter chips** (horizontal scrollable row):

| Chip         | Params                                           |
|--------------|--------------------------------------------------|
| All          | (default)                                        |
| Unallocated  | `unallocated=true` ⚠️ *API gap — see section 7*   |
| Pending      | `pending=true`                                   |
| Income       | client-side filter on positive `amount`          |
| Last 30 days | `date_from={30 days ago}`                        |

**List structure:** Grouped by `transaction_date` with sticky date headers.

**`TransactionRow.vue`:**

```
[ Party name              ] [ amount ]
[ allocation info · date  ] [ type   ]
```

Allocation info variants:
- `Unallocated — tap to assign` (italic, neutral-500) — when allocation points to the unallocated budget. Blue left border (3px, ocean-400).
- `From Budget Name` (budget name in ocean-600)
- `Split: Budget A, Budget B` — budget names are a tappable dotted-underline link that opens `SplitPopup`

**`SplitPopup.vue`:** Renders as an absolutely-positioned card anchored below the transaction row. Shows each allocation as `Budget Name ... $amount`, total row, closes on outside tap or Escape. On tablet/desktop this can be an inline expansion rather than a popup.

**Internal transactions:** Hidden by default. A "Show transfers" toggle in the filter row reveals them, styled differently (lighter, italic "Transfer" label instead of a party name).

**Search:** `GET /api/v1/transactions/?bank_account={uuid}&search={query}` — debounced 300ms.

### 4.6 Transaction Detail View (`/app/transactions/:id/`)

**API:** `GET /api/v1/transactions/:id/`

**Transactions are read-only records imported from bank statements. Users cannot create or delete transactions.**

**Hero block (read-only):**
```
Party name (from `party` field, falls back to `description` then `raw_description`)
$amount  (large, IBM Plex Mono, coral if negative)
date · PENDING badge (if pending) · account name
```

**Metadata section (mostly read-only):**
- Description — **editable** (`description` field, `PATCH /api/v1/transactions/:id/`)
- Raw description — read-only (`raw_description`)
- Transaction type — read-only (human-friendly label from `TransactionTypeEnum`)
- Balance after — read-only (`bank_account_posted_balance`)

**Allocations section:**

Fetch: `GET /api/v1/allocations/?transaction={uuid}`

Each allocation renders as an `AllocationCard`:
- Swipe-left-to-delete hint: `IconChevronLeft` + `IconTrash` at 40% opacity, top-left corner, 9px. On touch: swipe left reveals red "Remove" background. On desktop: small × button appears on hover in top-left.
- Budget name (tappable → navigates to that budget's detail)
- Amount input (editable, IBM Plex Mono, underlined when focused)
- Category picker row (tappable → opens category picker sheet)
- When only one allocation exists, the swipe hint is hidden (last allocation cannot be removed)

**Remaining indicator** (live, below allocations):
```
Fully allocated   $142.80 ✓      ← mint-50 bg, mint-600 text
Unassigned        $40.00 remaining ← ocean-50 bg, ocean-600 text
Over by           $5.00            ← coral-50 bg, coral-600 text
```

**"Add split" button:** `IconPlus` + "Add split" — adds a new `AllocationCard` with a budget picker prompt and amount pre-filled with the remaining unassigned amount. Selecting a budget calls `POST /api/v1/allocations/` with `{transaction, budget, amount, category}`.

**Editing an existing allocation amount:** `PATCH /api/v1/allocations/:id/` with `{amount}`. The backend must validate that the sum of all allocations for the transaction does not exceed `transaction.amount` — see API gap notes in section 7.

**Deleting an allocation:** `DELETE /api/v1/allocations/:id/` — not allowed when it is the last allocation on the transaction.

**Memo:** `PATCH /api/v1/transactions/:id/` `{memo}` — debounced autosave 800ms.

**Attachments:**
- "Attach photo" → file input, `PATCH /api/v1/transactions/:id/` multipart with `image`
- "Attach document" → file input, `PATCH /api/v1/transactions/:id/` multipart with `document`

**Footer note:** "Transactions are imported from bank statements and cannot be created or deleted."

### 4.7 Account View (`/app/account/`)

Three sections:

**Profile card:**
- Avatar initials circle (ocean-50 bg, ocean-600 text)
- Name + username
- Tappable → `/app/account/profile/` (edit name, username)

**Bank accounts list:**
- One row per account: colour dot + name + type/number meta + posted balance + unallocated amount ("$X free" in mint-600)
- "Add bank account" row with dashed ocean border

**Settings:**
- "Default account" → tappable → picker sheet → `PATCH /api/v1/users/me/` `{default_bank_account}` ⚠️ *API gap — see section 7*
- "Sign out" → clears auth store → redirect to `/app/login/`

### 4.8 Bank Account Detail View (`/app/account/bank-accounts/:id/`)

**API:** `GET /api/v1/bank-accounts/:id/`

**Hero balance grid (2×2, all read-only after creation):**
```
[ Posted balance ] [ Available balance ]
[ Unallocated    ] [ Currency          ]
```

**Details section:** account number (masked), bank name, created date — all read-only.

**Owners section:** list of usernames who share this account.

**Budgets section:** count of budgets + "View all budgets →" link that navigates to Budgets view filtered to this account.

**Edit (name only):** The "Edit" nav button opens an inline edit for the `name` field only. `PATCH /api/v1/bank-accounts/:id/` `{name}`. All other fields are immutable.

**Delete account:** Confirmation sheet (warns that all budgets, transactions, and allocations will be deleted) → `DELETE /api/v1/bank-accounts/:id/`.

### 4.9 Bank Account Create View (`/app/account/bank-accounts/create/`)

**API:** `POST /api/v1/bank-accounts/`

Fields:
- Account type — three-option grid: Checking / Savings / Credit card (`C` / `S` / `X`)
- Name (text, required)
- Bank — picker from `GET /api/v1/banks/` results. If list is empty or desired bank not found, allow free-text entry ⚠️ *may need backend support*
- Account number (optional, masked on display after save)
- Currency — picker from `GET /api/v1/currencies/`, default USD
- Posted balance (decimal, optional)
- Available balance (decimal, optional)

Footer note: "Balances are immutable after creation. An Unallocated budget is created automatically."

Submit → on success navigate to the new account's detail view.

---

## 5. Shared Components

### 5.1 `SchedulePicker.vue`

Used in both Budget Create and Budget Edit (funding schedule and refresh cycle fields).

**Props:**
```ts
interface SchedulePickerProps {
  modelValue: string   // RRULE string, e.g. "RRULE:FREQ=MONTHLY;BYMONTHDAY=1,15"
  label: string        // e.g. "Funding schedule" or "Refresh cycle"
}
emits: ['update:modelValue']
```

**Frequency segmented control:** Weekly | Monthly | Yearly

**Weekly options:**
- Interval select: Every week / Every 2 weeks / Every 4 weeks
- Day-of-week grid: Mo Tu We Th Fr Sa Su — multi-select, toggle on/off, minimum 1 selected
- Produces: `RRULE:FREQ=WEEKLY[;INTERVAL=N];BYDAY=MO,FR`

**Monthly options:**
- Interval select: Every month / Every 2 months / Every quarter (3) / Every 6 months
- Day-of-month grid: 31 numbered buttons (1–31) + "Last" button — **multi-select**, minimum 1 selected
- Produces: `RRULE:FREQ=MONTHLY[;INTERVAL=N];BYMONTHDAY=1,15` (or `-1` for Last)

**Yearly options:**
- Interval select: Every year / Every 2 years
- Month select (January–December)
- Day-of-month select (1st, 5th, 10th, 15th, 20th, 25th, Last day)
- Produces: `RRULE:FREQ=YEARLY[;INTERVAL=2];BYMONTH=5;BYMONTHDAY=15`

**Preview block** (always visible at bottom of picker):
- Human-readable text: "Every month on the 1st and 15th"
- RRULE string in IBM Plex Mono, muted — useful for debugging

The component is a pure RRULE string producer/consumer. It must also be able to parse an existing RRULE string back into its UI state for editing.

### 5.2 `MoneyAmount.vue`

```ts
interface MoneyAmountProps {
  amount: string       // decimal string from API e.g. "142.80"
  currency: string     // ISO 4217 e.g. "USD"
  size?: 'sm' | 'md' | 'lg' | 'hero'  // controls font-size
  showSign?: boolean   // prepend + for positive
  coloured?: boolean   // coral for negative, mint for positive
}
```

Always renders in IBM Plex Mono. Uses `Intl.NumberFormat` for locale-aware formatting.

### 5.3 `ConfirmSheet.vue`

Bottom sheet for destructive actions. Props: `title`, `message`, `confirmLabel` (default "Delete"), `confirmClass` (default coral). Emits `confirm` and `cancel`.

### 5.4 `AccountSwitcher.vue`

Bottom sheet triggered by tapping the `TopBar` centre block.
- Lists all accounts from `GET /api/v1/bank-accounts/`
- Each row: colour dot + name + type + unallocated amount
- Selected account highlighted with checkmark
- Selecting updates `accountContext` store → all views re-fetch with new `bank_account` param
- "Manage accounts →" navigates to `/app/account/`

---

## 6. State Management (Pinia)

### `stores/auth.ts`
```ts
state: {
  accessToken: string | null
  user: User | null
}
actions: login(), logout(), refreshToken()
```
`refreshToken()` calls `POST /api/token/refresh/` — the refresh token is in the httpOnly cookie so no token value needs to be sent in the body (backend reads it from cookie).

### `stores/accountContext.ts`
```ts
state: {
  activeBankAccountId: string | null   // UUID
  activeBankAccount: BankAccount | null
  unallocatedBudgetId: string | null   // UUID from BankAccount.unallocated_budget
}
```
On app boot: load from `localStorage`, then fetch `GET /api/v1/bank-accounts/` to validate and populate. If `user.default_bank_account` is set, use that as the initial value.

Every view that lists budgets, transactions, or allocations scoped to an account reads `accountContext.activeBankAccountId` and passes it as the `bank_account` query param.

### `stores/budgets.ts`
```ts
state: {
  budgets: Budget[]
  loading: boolean
  error: string | null
}
actions: fetchBudgets(bankAccountId), createBudget(), updateBudget(), deleteBudget()
```

### `stores/transactions.ts`
```ts
state: {
  transactions: Transaction[]
  loading: boolean
  filters: TransactionFilters
}
actions: fetchTransactions(params), fetchTransaction(id)
```

---

## 7. API Mapping & Known Gaps

### 7.1 Existing Endpoints Used

| Operation                   | Method + Path                                                                                                       |
|-----------------------------|---------------------------------------------------------------------------------------------------------------------|
| Login                       | `POST /api/token/`                                                                                                  |
| Refresh token               | `POST /api/token/refresh/`                                                                                          |
| Get current user            | `GET /api/v1/users/me/`                                                                                             |
| Update user                 | `PATCH /api/v1/users/me/`                                                                                           |
| List bank accounts          | `GET /api/v1/bank-accounts/`                                                                                        |
| Get bank account            | `GET /api/v1/bank-accounts/:id/`                                                                                    |
| Create bank account         | `POST /api/v1/bank-accounts/`                                                                                       |
| Update bank account name    | `PATCH /api/v1/bank-accounts/:id/`                                                                                  |
| Delete bank account         | `DELETE /api/v1/bank-accounts/:id/`                                                                                 |
| List banks                  | `GET /api/v1/banks/`                                                                                                |
| List budgets                | `GET /api/v1/budgets/?bank_account=&budget_type=&paused=&archived=`                                                 |
| Get budget                  | `GET /api/v1/budgets/:id/`                                                                                          |
| Create budget               | `POST /api/v1/budgets/`                                                                                             |
| Update budget               | `PATCH /api/v1/budgets/:id/`                                                                                        |
| Delete budget               | `DELETE /api/v1/budgets/:id/`                                                                                       |
| List transactions           | `GET /api/v1/transactions/?bank_account=&pending=&date_from=&date_to=&search=&ordering=`                            |
| Get transaction             | `GET /api/v1/transactions/:id/`                                                                                     |
| Update transaction          | `PATCH /api/v1/transactions/:id/` (description, memo, image, document only)                                         |
| List allocations            | `GET /api/v1/allocations/?transaction=&budget=`                                                                     |
| Create allocation           | `POST /api/v1/allocations/`                                                                                         |
| Update allocation           | `PATCH /api/v1/allocations/:id/` (budget, category, memo — amount immutable after create per spec, *see gap below*) |
| Delete allocation           | `DELETE /api/v1/allocations/:id/`                                                                                   |
| List internal transactions  | `GET /api/v1/internal-transactions/?bank_account=&src_budget=&dst_budget=`                                          |
| Create internal transaction | `POST /api/v1/internal-transactions/`                                                                               |
| List currencies             | `GET /api/v1/currencies/`                                                                                           |

### 7.2 API Gaps — Backend Extension Required

These items must be implemented before the corresponding UI features can function. Claude Code should flag these and implement stubs or mock data in the interim.

#### GAP-1: `default_bank_account` on User model
**Needed for:** App boot account selection, Account settings "Default account" row.
**Change:** Add `default_bank_account` (nullable FK to `BankAccount`) to the `User` model. Expose it on `GET /api/v1/users/me/` and accept it on `PATCH /api/v1/users/me/`.

#### GAP-2: `unallocated_budget` on BankAccount response
**Needed for:** `TopBar` unallocated amount, identifying unallocated allocations in transaction rows.
**Change:** The `BankAccount` serializer should include `unallocated_budget` (UUID of the auto-created unallocated budget). Verify this is already returned — if not, add it as a read-only field.

#### GAP-3: `allocation_status` filter on transactions
**Needed for:** "Unallocated" filter chip in transactions view.
**Change:** Add `unallocated=true` query param to `GET /api/v1/transactions/` that returns only transactions whose sole allocation points to the account's unallocated budget.

#### GAP-4: Allocation `amount` mutability
**Current:** The OpenAPI spec marks `amount` as required on create and `budget`/`category`/`memo` as updatable after creation, implying `amount` is immutable after create.
**Needed for:** Editing split amounts on the transaction detail screen.
**Change:** Decide whether `amount` should be mutable via `PATCH`. If yes, update the serializer to allow it, with validation that the sum of all allocations for the transaction does not exceed `transaction.amount`. The validation must query sibling allocations, not just the patched one. If amount remains immutable, the UI must delete and re-create allocations to change amounts.

#### GAP-5: `funding_type` enum values
**Needed for:** Budget create/edit funding type toggle (Auto vs Fixed).
**Change:** Confirm the valid values for the `funding_type` field on `Budget`. The UI assumes `'auto'` and `'fixed'` — verify these match the backend enum and update if different.

#### GAP-6: `recurrence_schedule` and `funding_schedule` format
**Needed for:** `SchedulePicker` round-trip (parse RRULE from API, display in picker, save back).
**Change:** Confirm both fields store and accept RFC 2445 RRULE strings (as produced by `django-recurrence`). The frontend `SchedulePicker` produces strings in the form `RRULE:FREQ=MONTHLY;BYMONTHDAY=1,15` — verify the backend accepts and stores this format verbatim.

#### GAP-7: Bank free-text entry
**Needed for:** Bank account create form when desired bank is not in the `GET /api/v1/banks/` list.
**Change:** Banks are admin-managed reference data. Either (a) add a mechanism for users to request a new bank, or (b) allow a free-text `bank_name` override on account creation. Discuss with product owner. In the interim the UI shows "Your bank isn't listed — contact support."

---

## 8. API Client (`src/api/client.ts`)

```ts
// Responsibilities:
// 1. Attach Authorization: Bearer {accessToken} to every request
// 2. On 401 response: call POST /api/token/refresh/, retry original request once
// 3. On second 401: clear auth store, redirect to /app/login/
// 4. Paginated list responses: auto-follow `next` cursor or expose pagination state
// 5. Money fields: always treat as strings (decimal), never parse to float

const BASE = '/api/v1'

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  options?: RequestInit
): Promise<T>

// Convenience wrappers
export const api = {
  get:    <T>(path: string) => request<T>('GET', path),
  post:   <T>(path: string, body: unknown) => request<T>('POST', path, body),
  patch:  <T>(path: string, body: unknown) => request<T>('PATCH', path, body),
  put:    <T>(path: string, body: unknown) => request<T>('PUT', path, body),
  delete: <T>(path: string) => request<T>('DELETE', path),
}
```

**Important:** All monetary values from the API are decimal strings (e.g. `"142.80"`). Never parse to `Number` for arithmetic — use a decimal library or string-based arithmetic to avoid float precision issues. Display using `Intl.NumberFormat`.

---

## 9. TypeScript Types (`src/types/api.ts`)

```ts
export interface BankAccount {
  id: string
  name: string
  bank: string                // UUID
  account_type: 'C' | 'S' | 'X'
  account_number: string | null
  currency: string
  posted_balance: string
  posted_balance_currency: string
  available_balance: string
  available_balance_currency: string
  unallocated_budget: string  // UUID — GAP-2: verify this is returned
  created_at: string
  modified_at: string
}

export interface Budget {
  id: string
  name: string
  bank_account: string        // UUID
  budget_type: 'G' | 'R' | 'A'
  balance: string             // read-only, managed by signals
  balance_currency: string
  target_balance: string | null
  target_balance_currency: string
  funding_type: string        // GAP-5: confirm enum values
  target_date: string | null  // ISO date
  with_fillup_goal: boolean
  fillup_goal: string | null  // UUID of associated fill-up budget
  paused: boolean
  funding_schedule: string    // RRULE string
  recurrence_schedule: string | null  // RRULE string
  memo: string | null
  auto_spend: unknown
  created_at: string
  modified_at: string
}

export interface Transaction {
  id: string
  bank_account: string        // UUID
  amount: string
  amount_currency: string
  party: string | null        // read-only, derived
  transaction_date: string
  transaction_type: TransactionType | ''
  pending: boolean
  memo: string | null
  raw_description: string
  description: string
  bank_account_posted_balance: string
  bank_account_posted_balance_currency: string
  bank_account_available_balance: string
  bank_account_available_balance_currency: string
  image: string | null        // URL
  document: string | null     // URL
  created_at: string
  modified_at: string
}

export interface TransactionAllocation {
  id: string
  transaction: string         // UUID
  budget: string | null       // UUID, null = unallocated
  amount: string
  amount_currency: string
  budget_balance: string      // read-only, balance after this allocation
  budget_balance_currency: string
  category: CategoryEnum | null
  memo: string | null
  created_at: string
  modified_at: string
}

export interface InternalTransaction {
  id: string
  bank_account: string        // UUID
  amount: string
  amount_currency: string
  src_budget: string          // UUID
  dst_budget: string          // UUID
  actor: string               // username
  src_budget_balance: string
  dst_budget_balance: string
  created_at: string
  modified_at: string
}

export interface Bank {
  id: string
  name: string
}

export interface User {
  username: string
  name: string
  url: string
  default_bank_account?: string | null  // UUID — GAP-1
}

export type TransactionType =
  | 'signature_purchase' | 'ach' | 'round-up_transfer'
  | 'protected_goal_account_transfer' | 'fee' | 'pin_purchase'
  | 'signature_credit' | 'interest_credit' | 'shared_transfer'
  | 'courtesy_credit' | 'atm_withdrawal' | 'bill_payment'
  | 'bank_generated_credit' | 'wire_transfer' | 'check_deposit'
  | 'check' | 'c2c' | 'migration_interbank_transfer' | 'balance_sweep'
  | 'ach_reversal' | 'adjustment' | 'signature_return' | 'fx_order'

// Human-friendly labels for TransactionType
export const TRANSACTION_TYPE_LABELS: Record<string, string> = {
  signature_purchase: 'Signature purchase',
  ach: 'ACH transfer',
  'round-up_transfer': 'Round-up transfer',
  fee: 'Fee',
  pin_purchase: 'PIN purchase',
  signature_credit: 'Credit',
  interest_credit: 'Interest',
  atm_withdrawal: 'ATM withdrawal',
  bill_payment: 'Bill payment',
  check_deposit: 'Check deposit',
  check: 'Check',
  wire_transfer: 'Wire transfer',
  // ... add remainder
}
```

---

## 10. Routing

```ts
// router/index.ts
const routes = [
  { path: '/app/login/',                    component: LoginView,               meta: { public: true } },
  { path: '/app/',                          component: OverviewView              },
  { path: '/app/budgets/',                  component: BudgetsView               },
  { path: '/app/budgets/create/',           component: BudgetCreateView          },
  { path: '/app/budgets/:id/',              component: BudgetDetailView          },
  { path: '/app/transactions/',             component: TransactionsView          },
  { path: '/app/transactions/:id/',         component: TransactionDetailView     },
  { path: '/app/account/',                  component: AccountView               },
  { path: '/app/account/profile/',          component: UserProfileView           },
  { path: '/app/account/bank-accounts/create/', component: BankAccountCreateView },
  { path: '/app/account/bank-accounts/:id/',    component: BankAccountDetailView },
]

// Navigation guard: redirect to /app/login/ if no accessToken
// On /app/login/ with valid token: redirect to /app/
```

---

## 11. Responsive Behaviour Notes

### Budget list
- **Mobile:** Single column cards
- **Tablet:** Two columns of cards
- **Desktop:** Two columns + budget detail slide-in panel (master/detail)

### Transaction list
- **Mobile:** Full-width rows, split popup as floating card
- **Tablet/Desktop:** Two-column: list left, detail right (no navigation to separate view)

### Account switcher
- **Mobile:** Bottom sheet
- **Tablet/Desktop:** Dropdown from header or left sidebar section

### Fill-up band
- Same treatment at all breakpoints — always attached to bottom of parent card

### Schedule picker
- **Mobile:** Full-width, stacked
- **Tablet/Desktop:** Can be shown inline in a two-column form layout

---

## 12. Accessibility & Edge Cases

- All icon-only buttons must have `aria-label`
- `MoneyAmount` must use `aria-label` with the unformatted value for screen readers
- Empty states: each list view needs an `EmptyState` component variant (no budgets yet, no transactions yet)
- Loading states: skeleton loaders on initial fetch, not spinners
- Pagination: all list endpoints are paginated — implement infinite scroll (IntersectionObserver on last row triggers fetch of `next` page URL)
- Error states: API errors surface as inline banners, not alerts
- The unallocated budget (fetched by UUID from `BankAccount.unallocated_budget`) must be excluded from all budget pickers and lists

---

## 13. Development Notes for Claude Code

1. **Start with `AppShell`, `TopBar`, and routing** — these unblock all other views.
2. **`accountContext` store is foundational** — every data fetch depends on it. Implement and test this before any views.
3. **`SchedulePicker` is self-contained** — build and test it in isolation before embedding in budget forms.
4. **Money arithmetic:** Use string comparison or a library like `decimal.js` for any arithmetic on monetary values. Never `parseFloat`.
5. **API gaps (section 7):** Where a gap affects a feature, implement the feature with a clearly marked `// TODO: GAP-N` comment and a sensible fallback (e.g. hardcode `default_bank_account` to the first account returned).
6. **`budget_type = 'A'`** (ASSOCIATED_FILLUP_GOAL) budgets must never appear in the budget list as standalone rows. Filter them out in the store after fetch. They appear only as the `fillupBudget` prop on their parent's `BudgetCard`.
7. **Immutability:** `bank_account`, `budget_type`, `currency`, `account_number`, `posted_balance`, and `available_balance` are all immutable after creation. Render them as read-only in all edit forms.
8. **Transactions are read-only** — no create, no delete. The only mutations are `PATCH` for `description`, `memo`, `image`, `document` on the transaction itself, plus create/update/delete on its allocations.
9. **Internal transactions** (`/api/v1/internal-transactions/`) are write-once — no update or delete endpoint exists. To reverse a transfer, create a new internal transaction with `src_budget` and `dst_budget` swapped.
