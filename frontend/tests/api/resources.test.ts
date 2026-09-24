//
// Per-resource API module tests: one table row per exported function in
// `src/api/*.ts` that makes a request.  Each row names the call, the
// HTTP method, the path under `/api/v1` (with trailing slash and query
// string), and the JSON body sent.  Adding an API function means adding
// one row here.
//
// `qs` and `fetchAllPages` (`api/util.ts`) and `adminEmail`
// (`api/config.ts`) have their own tests in `util.test.ts`.
//

// 3rd party imports
//
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it } from "vitest";

// app imports
//
import { listAllocations } from "@/api/allocations";
import { createApiKey, listApiKeys, revokeApiKey } from "@/api/apiKeys";
import {
  createBankAccount,
  deleteBankAccount,
  fundingSummary,
  getBankAccount,
  listBankAccounts,
  runFunding,
  updateBankAccount,
} from "@/api/bankAccounts";
import { getBank, listBanks } from "@/api/banks";
import {
  archiveBudget,
  createBudget,
  deleteBudget,
  getBudget,
  listBudgets,
  updateBudget,
} from "@/api/budgets";
import { listCurrencies } from "@/api/currencies";
import {
  createInternalTransaction,
  getInternalTransaction,
  listInternalTransactions,
} from "@/api/internalTransactions";
import {
  cancelInvitation,
  listAccountInvitations,
  listMyInvitations,
  sendInvitation,
} from "@/api/invitations";
import {
  getChannelPreferences,
  getNotificationPreferences,
  updateChannelPreference,
  updateNotificationPreference,
} from "@/api/notifications";
import {
  getTransaction,
  listTransactions,
  listTransactionsNext,
  splitTransaction,
  updateTransaction,
  uploadTransactionAttachment,
} from "@/api/transactions";
import { changeEmail, changePassword, getCurrentUser, updateCurrentUser } from "@/api/users";
import { TEST_TOKEN, withAuth } from "../helpers";
import { lastRequest, server } from "../mocks/server";

////////////////////////////////////////////////////////////////////////
//
type Method = "GET" | "POST" | "PATCH" | "DELETE";

interface Row {
  name: string;
  call: () => Promise<unknown>;
  method: Method;
  // Path under /api/v1, including the query string.
  path: string;
  // Expected request body as logged: parsed JSON, or field → value for
  // multipart.  `undefined` means no body.
  //
  body?: unknown;
}

const ID = "11111111-1111-4111-8111-111111111111";

const rows: Row[] = [
  // allocations.ts
  {
    name: "listAllocations",
    call: () => listAllocations({ transaction: ID, uncategorized: true }),
    method: "GET",
    path: `/allocations/?transaction=${ID}&uncategorized=true`,
  },
  // apiKeys.ts
  { name: "listApiKeys", call: () => listApiKeys(), method: "GET", path: "/users/me/api-keys/" },
  {
    name: "createApiKey",
    call: () => createApiKey("importer", 90),
    method: "POST",
    path: "/users/me/api-keys/",
    body: { name: "importer", expiry_days: 90 },
  },
  {
    name: "createApiKey (never expires)",
    call: () => createApiKey("forever", null),
    method: "POST",
    path: "/users/me/api-keys/",
    body: { name: "forever", expiry_days: null },
  },
  {
    name: "revokeApiKey",
    call: () => revokeApiKey(ID),
    method: "POST",
    path: `/users/me/api-keys/${ID}/revoke/`,
  },
  // bankAccounts.ts
  {
    name: "listBankAccounts",
    call: () => listBankAccounts(),
    method: "GET",
    path: "/bank-accounts/",
  },
  {
    name: "getBankAccount",
    call: () => getBankAccount(ID),
    method: "GET",
    path: `/bank-accounts/${ID}/`,
  },
  {
    name: "createBankAccount",
    call: () => createBankAccount({ name: "Joint", account_type: "C" }),
    method: "POST",
    path: "/bank-accounts/",
    body: { name: "Joint", account_type: "C" },
  },
  {
    name: "updateBankAccount",
    call: () => updateBankAccount(ID, { name: "Renamed" }),
    method: "PATCH",
    path: `/bank-accounts/${ID}/`,
    body: { name: "Renamed" },
  },
  {
    name: "deleteBankAccount",
    call: () => deleteBankAccount(ID),
    method: "DELETE",
    path: `/bank-accounts/${ID}/`,
  },
  {
    name: "fundingSummary",
    call: () => fundingSummary(ID),
    method: "GET",
    path: `/bank-accounts/${ID}/funding-summary/`,
  },
  {
    name: "runFunding",
    call: () => runFunding(ID),
    method: "POST",
    path: `/bank-accounts/${ID}/run-funding/`,
  },
  // banks.ts
  { name: "listBanks", call: () => listBanks(), method: "GET", path: "/banks/" },
  { name: "getBank", call: () => getBank(ID), method: "GET", path: `/banks/${ID}/` },
  // budgets.ts
  {
    name: "listBudgets",
    call: () => listBudgets({ bank_account: ID, archived: false, ordering: "name" }),
    method: "GET",
    path: `/budgets/?bank_account=${ID}&archived=false&ordering=name`,
  },
  { name: "listBudgets (no params)", call: () => listBudgets(), method: "GET", path: "/budgets/" },
  { name: "getBudget", call: () => getBudget(ID), method: "GET", path: `/budgets/${ID}/` },
  {
    name: "createBudget",
    call: () => createBudget({ name: "Rent", budget_type: "R", target_balance: "1500.00" }),
    method: "POST",
    path: "/budgets/",
    body: { name: "Rent", budget_type: "R", target_balance: "1500.00" },
  },
  {
    name: "updateBudget",
    call: () => updateBudget(ID, { paused: true }),
    method: "PATCH",
    path: `/budgets/${ID}/`,
    body: { paused: true },
  },
  { name: "deleteBudget", call: () => deleteBudget(ID), method: "DELETE", path: `/budgets/${ID}/` },
  {
    name: "archiveBudget",
    call: () => archiveBudget(ID),
    method: "POST",
    path: `/budgets/${ID}/archive/`,
  },
  // currencies.ts
  { name: "listCurrencies", call: () => listCurrencies(), method: "GET", path: "/currencies/" },
  // internalTransactions.ts
  {
    name: "listInternalTransactions",
    call: () => listInternalTransactions({ budget: ID, date_from: "2026-01-01" }),
    method: "GET",
    path: `/internal-transactions/?budget=${ID}&date_from=2026-01-01`,
  },
  {
    name: "getInternalTransaction",
    call: () => getInternalTransaction(ID),
    method: "GET",
    path: `/internal-transactions/${ID}/`,
  },
  {
    name: "createInternalTransaction",
    call: () => createInternalTransaction({ amount: "25.00", src_budget: "s", dst_budget: "d" }),
    method: "POST",
    path: "/internal-transactions/",
    body: { amount: "25.00", src_budget: "s", dst_budget: "d" },
  },
  // invitations.ts
  {
    name: "listAccountInvitations",
    call: () => listAccountInvitations(ID),
    method: "GET",
    path: `/bank-accounts/${ID}/invitations/`,
  },
  {
    name: "sendInvitation",
    call: () => sendInvitation(ID, "friend@example.com"),
    method: "POST",
    path: `/bank-accounts/${ID}/invite/`,
    body: { invitee_email: "friend@example.com" },
  },
  {
    name: "cancelInvitation",
    call: () => cancelInvitation(ID, "tok123"),
    method: "POST",
    path: `/bank-accounts/${ID}/invitations/tok123/cancel/`,
  },
  {
    name: "listMyInvitations",
    call: () => listMyInvitations(),
    method: "GET",
    path: "/users/me/invitations/",
  },
  // notifications.ts
  {
    name: "getNotificationPreferences",
    call: () => getNotificationPreferences(),
    method: "GET",
    path: "/notification-preferences/",
  },
  {
    name: "updateNotificationPreference",
    call: () => updateNotificationPreference("budget overdrawn", "digest"),
    method: "PATCH",
    path: "/notification-preferences/budget%20overdrawn/",
    body: { delivery_mode: "digest" },
  },
  {
    name: "getChannelPreferences",
    call: () => getChannelPreferences(),
    method: "GET",
    path: "/channel-preferences/",
  },
  {
    name: "updateChannelPreference",
    call: () => updateChannelPreference("email", "weekly"),
    method: "PATCH",
    path: "/channel-preferences/email/",
    body: { digest_frequency: "weekly" },
  },
  // transactions.ts
  {
    name: "listTransactions",
    call: () => listTransactions({ bank_account: ID, pending: false, search: "coffee shop" }),
    method: "GET",
    path: `/transactions/?bank_account=${ID}&pending=false&search=coffee+shop`,
  },
  {
    name: "listTransactionsNext",
    call: () => listTransactionsNext(`https://mibudge.example/api/v1/transactions/?page=2`),
    method: "GET",
    path: "/transactions/?page=2",
  },
  {
    name: "getTransaction",
    call: () => getTransaction(ID),
    method: "GET",
    path: `/transactions/${ID}/`,
  },
  {
    name: "updateTransaction",
    call: () => updateTransaction(ID, { description: "Lunch", memo: "with Sam" }),
    method: "PATCH",
    path: `/transactions/${ID}/`,
    body: { description: "Lunch", memo: "with Sam" },
  },
  {
    name: "uploadTransactionAttachment",
    call: () => uploadTransactionAttachment(ID, "image", new File(["png"], "receipt.png")),
    method: "PATCH",
    path: `/transactions/${ID}/`,
    body: { image: "receipt.png" },
  },
  {
    name: "splitTransaction",
    call: () => splitTransaction(ID, { [ID]: "-5.00", other: "-7.34" }),
    method: "POST",
    path: `/transactions/${ID}/splits/`,
    body: { splits: { [ID]: "-5.00", other: "-7.34" } },
  },
  // users.ts
  { name: "getCurrentUser", call: () => getCurrentUser(), method: "GET", path: "/users/me/" },
  {
    name: "updateCurrentUser",
    call: () => updateCurrentUser({ timezone: "Europe/Paris" }),
    method: "PATCH",
    path: "/users/me/",
    body: { timezone: "Europe/Paris" },
  },
  {
    name: "changePassword",
    call: () => changePassword({ current_password: "a", new_password: "b", confirm_password: "b" }),
    method: "POST",
    path: "/users/me/change-password/",
    body: { current_password: "a", new_password: "b", confirm_password: "b" },
  },
  {
    name: "changeEmail",
    call: () => changeEmail("new@example.com"),
    method: "POST",
    path: "/users/me/change-email/",
    body: { new_email: "new@example.com" },
  },
];

////////////////////////////////////////////////////////////////////////
//
describe("API modules", () => {
  beforeEach(() => {
    withAuth();
  });

  // GIVEN: a per-resource API function
  // WHEN:  it is called
  // THEN:  it sends the expected method, path, query string and JSON body
  //        under `/api/v1` with the session's access token
  //  AND:  it resolves to the parsed response body
  //
  it.each(rows)("$name", async ({ call, method, path, body }) => {
    // Answer this exact endpoint with a unique payload so the assertion
    // proves the function returns what the server sent.
    //
    const pathname = `/api/v1${path.split("?")[0]}`;
    const payload = { sentinel: pathname, method };
    const verb = method.toLowerCase() as Lowercase<Method>;
    server.use(http[verb](pathname, () => HttpResponse.json(payload)));

    const result = await call();

    const req = await lastRequest();
    expect(req?.method).toBe(method);
    expect(req?.path).toBe(`/api/v1${path}`);
    expect(req?.body).toEqual(body);
    expect(req?.headers.authorization).toBe(`Bearer ${TEST_TOKEN}`);
    expect(result).toEqual(payload);
  });
});
