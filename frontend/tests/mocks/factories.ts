//
// DTO factories for the mock REST API -- the SPA-side analogue of the
// factory-boy factories in `app/tests/`.
//
// Each `make*` returns a schema-valid object typed by the generated DTO
// types (`src/api/dto.ts`, from `docs/openapi.yaml`), with any field
// overridable through a `Partial<...>`.  Money values are decimal strings
// (`"12.34"`), as the API sends them.  UUIDs come from a per-process
// sequence, so every object is distinct and ids are stable to read in
// failure output.
//

// app imports
//
import type {
  AllocationDto as TransactionAllocation,
  ApiKeyDto as APIKey,
  BankAccountDto as BankAccount,
  BankDto as Bank,
  BudgetDto as Budget,
  ChannelPreferenceDto as ChannelPreference,
  FundingRunResultDto,
  FundingSummaryDto as FundingSummary,
  InternalTransactionDto as InternalTransaction,
  InvitationDto as BankAccountInvitation,
  NotificationPreferenceDto as NotificationPreference,
  Page as Paginated,
  TransactionCategoryDto,
  TransactionDto as Transaction,
  UserDto as User,
} from "@/api/dto";

////////////////////////////////////////////////////////////////////////
//
const TIMESTAMP = "2026-09-01T12:00:00Z";

let seq = 0;

////////////////////////////////////////////////////////////////////////
//
// Next UUID in the sequence: `00000000-0000-4000-8000-000000000001`, ...
//
export function uuid(): string {
  seq += 1;
  return `00000000-0000-4000-8000-${String(seq).padStart(12, "0")}`;
}

////////////////////////////////////////////////////////////////////////
//
export function makeUser(overrides: Partial<User> = {}): User {
  const username = overrides.username ?? `user${seq + 1}`;
  return {
    username,
    email: `${username}@example.com`,
    name: "Test User",
    url: `http://localhost/api/v1/users/${username}/`,
    default_bank_account: null,
    timezone: "America/New_York",
    has_usable_password: true,
    ...overrides,
  };
}

////////////////////////////////////////////////////////////////////////
//
export function makeBank(overrides: Partial<Bank> = {}): Bank {
  return {
    id: uuid(),
    name: "Test Bank",
    routing_number: "021000021",
    default_currency: "USD",
    created_at: TIMESTAMP,
    modified_at: TIMESTAMP,
    ...overrides,
  };
}

////////////////////////////////////////////////////////////////////////
//
export function makeBankAccount(overrides: Partial<BankAccount> = {}): BankAccount {
  return {
    id: uuid(),
    name: "Checking",
    bank: uuid(),
    owners: ["1"],
    account_type: "C",
    account_number: null,
    currency: "USD",
    posted_balance: "1000.00",
    posted_balance_currency: "USD",
    available_balance: "1000.00",
    available_balance_currency: "USD",
    unallocated_budget: uuid(),
    auto_funding_enabled: true,
    last_imported_at: null,
    last_posted_through: null,
    created_at: TIMESTAMP,
    modified_at: TIMESTAMP,
    ...overrides,
  };
}

////////////////////////////////////////////////////////////////////////
//
export function makeBudget(overrides: Partial<Budget> = {}): Budget {
  return {
    id: uuid(),
    name: "Groceries",
    bank_account: uuid(),
    budget_type: "G",
    balance: "100.00",
    balance_currency: "USD",
    funded_amount: "100.00",
    funded_amount_currency: "USD",
    target_balance: "500.00",
    target_balance_currency: "USD",
    funding_amount: null,
    funding_amount_currency: "USD",
    funding_type: "D",
    target_date: null,
    fillup_goal: null,
    complete: false,
    paused: false,
    archived: false,
    archived_at: null,
    funding_schedule: "RRULE:FREQ=MONTHLY;BYMONTHDAY=1",
    recurrence_schedule: null,
    memo: null,
    auto_spend: [],
    next_funding: null,
    next_recurrence: null,
    funding_pace: null,
    created_at: TIMESTAMP,
    modified_at: TIMESTAMP,
    ...overrides,
  };
}

////////////////////////////////////////////////////////////////////////
//
export function makeTransaction(overrides: Partial<Transaction> = {}): Transaction {
  return {
    id: uuid(),
    bank_account: uuid(),
    amount: "-12.34",
    amount_currency: "USD",
    party: null,
    posted_date: TIMESTAMP,
    transaction_date: TIMESTAMP,
    transaction_type: "signature_purchase",
    pending: false,
    memo: null,
    raw_description: "COFFEE SHOP 123",
    description: "Coffee Shop",
    description_user_edited: false,
    category: null,
    category_full_name: null,
    merchant_name: null,
    merchant_intermediary: null,
    merchant_address: null,
    merchant_city: null,
    merchant_region: null,
    merchant_country: null,
    merchant_latitude: null,
    merchant_longitude: null,
    merchant_category: null,
    merchant_category_code: null,
    virtual_card_number: null,
    has_details: false,
    bank_transaction_id: null,
    // The schema types this as a string; the server sends `null` for an
    // unlinked transaction.
    linked_transaction: null as unknown as string,
    bank_account_posted_balance: "987.66",
    bank_account_posted_balance_currency: "USD",
    bank_account_available_balance: "987.66",
    bank_account_available_balance_currency: "USD",
    image: null,
    document: null,
    created_at: TIMESTAMP,
    modified_at: TIMESTAMP,
    ...overrides,
  };
}

////////////////////////////////////////////////////////////////////////
//
export function makeAllocation(
  overrides: Partial<TransactionAllocation> = {},
): TransactionAllocation {
  return {
    id: uuid(),
    transaction: uuid(),
    budget: uuid(),
    amount: "-12.34",
    amount_currency: "USD",
    budget_balance: "87.66",
    budget_balance_currency: "USD",
    category: null,
    category_full_name: null,
    memo: null,
    created_at: TIMESTAMP,
    modified_at: TIMESTAMP,
    ...overrides,
  };
}

////////////////////////////////////////////////////////////////////////
//
export function makeInternalTransaction(
  overrides: Partial<InternalTransaction> = {},
): InternalTransaction {
  return {
    id: uuid(),
    bank_account: uuid(),
    amount: "25.00",
    amount_currency: "USD",
    src_budget: uuid(),
    dst_budget: uuid(),
    actor: 1,
    effective_date: TIMESTAMP,
    src_budget_balance: "75.00",
    src_budget_balance_currency: "USD",
    dst_budget_balance: "125.00",
    dst_budget_balance_currency: "USD",
    created_at: TIMESTAMP,
    modified_at: TIMESTAMP,
    ...overrides,
  };
}

////////////////////////////////////////////////////////////////////////
//
export function makeFundingSummary(overrides: Partial<FundingSummary> = {}): FundingSummary {
  return { schedules: [], total_amount: "0.00", currency: "USD", ...overrides };
}

////////////////////////////////////////////////////////////////////////
//
export function makeFundingRunResult(
  overrides: Partial<FundingRunResultDto> = {},
): FundingRunResultDto {
  return {
    transfers: 0,
    occurrences_completed: 0,
    occurrences_partial: 0,
    warnings: [],
    skipped_budgets: [],
    ...overrides,
  };
}

////////////////////////////////////////////////////////////////////////
//
export function makeCategory(
  overrides: Partial<TransactionCategoryDto> = {},
): TransactionCategoryDto {
  return {
    id: uuid(),
    group: "Food",
    name: "Groceries",
    full_name: "Food : Groceries",
    // Global rows have no owner; the schema types this as a string.
    owner: null as unknown as string,
    archived: false,
    created_at: TIMESTAMP,
    modified_at: TIMESTAMP,
    ...overrides,
  };
}

////////////////////////////////////////////////////////////////////////
//
export function makeApiKey(overrides: Partial<APIKey> = {}): APIKey {
  return {
    uuid: uuid(),
    name: "importer",
    prefix: "abcd1234",
    expires_at: null,
    last_used_at: null,
    revoked_at: null,
    created_at: TIMESTAMP,
    ...overrides,
  };
}

////////////////////////////////////////////////////////////////////////
//
export function makeInvitation(
  overrides: Partial<BankAccountInvitation> = {},
): BankAccountInvitation {
  return {
    id: uuid(),
    token: uuid(),
    bank_account_id: uuid(),
    bank_account_name: "Checking",
    invitee_email: "invitee@example.com",
    invited_by: "owner@example.com",
    status: "pending",
    expires_at: "2026-10-01T12:00:00Z",
    accepted_at: null,
    declined_at: null,
    cancelled_at: null,
    created_at: TIMESTAMP,
    modified_at: TIMESTAMP,
    ...overrides,
  };
}

////////////////////////////////////////////////////////////////////////
//
export function makeNotificationPreference(
  overrides: Partial<NotificationPreference> = {},
): NotificationPreference {
  return {
    kind: "budget_overdrawn",
    display_name: "Budget overdrawn",
    can_suppress: true,
    delivery_mode: "immediate",
    ...overrides,
  };
}

////////////////////////////////////////////////////////////////////////
//
export function makeChannelPreference(
  overrides: Partial<ChannelPreference> = {},
): ChannelPreference {
  return {
    channel: "email",
    display_name: "Email",
    digest_frequency: "daily_evening",
    ...overrides,
  };
}

////////////////////////////////////////////////////////////////////////
//
// DRF pagination envelope around `results`.  A single page by default;
// pass `next` to model a multi-page result.
//
export function makePage<T>(results: T[], overrides: Partial<Paginated<T>> = {}): Paginated<T> {
  return { count: results.length, next: null, previous: null, results, ...overrides };
}
