//
// Resource module tests: one table row per endpoint function in
// `src/api/resources/*.ts`, called through the `api` registry.  Each row
// names the call, the HTTP method, the path under `/api/v1` (with
// trailing slash and query string), and the JSON body sent.  Adding an
// endpoint function means adding one row here.
//
// The token endpoints (`api.auth`) and pagination (`api.pages`) are
// covered in `http.test.ts`.
//

// 3rd party imports
//
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it } from "vitest";

// app imports
//
import { api } from "@/api";
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
    name: "allocations.list",
    call: () => api.allocations.list({ transaction: ID, uncategorized: true }),
    method: "GET",
    path: `/allocations/?transaction=${ID}&uncategorized=true`,
  },
  // apiKeys.ts
  {
    name: "apiKeys.list",
    call: () => api.apiKeys.list(),
    method: "GET",
    path: "/users/me/api-keys/",
  },
  {
    name: "apiKeys.create",
    call: () => api.apiKeys.create({ name: "importer", expiry_days: 90 }),
    method: "POST",
    path: "/users/me/api-keys/",
    body: { name: "importer", expiry_days: 90 },
  },
  {
    name: "apiKeys.create (never expires)",
    call: () => api.apiKeys.create({ name: "forever", expiry_days: null }),
    method: "POST",
    path: "/users/me/api-keys/",
    body: { name: "forever", expiry_days: null },
  },
  {
    name: "apiKeys.revoke",
    call: () => api.apiKeys.revoke(ID),
    method: "POST",
    path: `/users/me/api-keys/${ID}/revoke/`,
  },
  // bankAccounts.ts
  {
    name: "bankAccounts.list",
    call: () => api.bankAccounts.list(),
    method: "GET",
    path: "/bank-accounts/",
  },
  {
    name: "bankAccounts.get",
    call: () => api.bankAccounts.get(ID),
    method: "GET",
    path: `/bank-accounts/${ID}/`,
  },
  {
    name: "bankAccounts.create",
    call: () => api.bankAccounts.create({ name: "Joint", bank: ID, account_type: "C" }),
    method: "POST",
    path: "/bank-accounts/",
    body: { name: "Joint", bank: ID, account_type: "C" },
  },
  {
    name: "bankAccounts.update",
    call: () => api.bankAccounts.update(ID, { name: "Renamed" }),
    method: "PATCH",
    path: `/bank-accounts/${ID}/`,
    body: { name: "Renamed" },
  },
  {
    name: "bankAccounts.remove",
    call: () => api.bankAccounts.remove(ID),
    method: "DELETE",
    path: `/bank-accounts/${ID}/`,
  },
  {
    name: "bankAccounts.fundingSummary",
    call: () => api.bankAccounts.fundingSummary(ID),
    method: "GET",
    path: `/bank-accounts/${ID}/funding-summary/`,
  },
  {
    name: "bankAccounts.runFunding",
    call: () => api.bankAccounts.runFunding(ID),
    method: "POST",
    path: `/bank-accounts/${ID}/run-funding/`,
  },
  // banks.ts
  { name: "banks.list", call: () => api.banks.list(), method: "GET", path: "/banks/" },
  { name: "banks.get", call: () => api.banks.get(ID), method: "GET", path: `/banks/${ID}/` },
  // budgets.ts
  {
    name: "budgets.list",
    call: () => api.budgets.list({ bank_account: ID, archived: false, ordering: "name" }),
    method: "GET",
    path: `/budgets/?bank_account=${ID}&archived=false&ordering=name`,
  },
  {
    name: "budgets.list (no params)",
    call: () => api.budgets.list(),
    method: "GET",
    path: "/budgets/",
  },
  { name: "budgets.get", call: () => api.budgets.get(ID), method: "GET", path: `/budgets/${ID}/` },
  {
    name: "budgets.create",
    call: () =>
      api.budgets.create({
        name: "Rent",
        bank_account: ID,
        budget_type: "R",
        target_balance: "1500.00",
      }),
    method: "POST",
    path: "/budgets/",
    body: { name: "Rent", bank_account: ID, budget_type: "R", target_balance: "1500.00" },
  },
  {
    name: "budgets.update",
    call: () => api.budgets.update(ID, { paused: true }),
    method: "PATCH",
    path: `/budgets/${ID}/`,
    body: { paused: true },
  },
  {
    name: "budgets.archive",
    call: () => api.budgets.archive(ID),
    method: "POST",
    path: `/budgets/${ID}/archive/`,
  },
  // internalTransactions.ts
  {
    name: "internalTransactions.list",
    call: () => api.internalTransactions.list({ budget: ID, date_from: "2026-01-01" }),
    method: "GET",
    path: `/internal-transactions/?budget=${ID}&date_from=2026-01-01`,
  },
  {
    name: "internalTransactions.create",
    call: () =>
      api.internalTransactions.create({
        bank_account: ID,
        amount: "25.00",
        src_budget: "s",
        dst_budget: "d",
      }),
    method: "POST",
    path: "/internal-transactions/",
    body: { bank_account: ID, amount: "25.00", src_budget: "s", dst_budget: "d" },
  },
  // invitations.ts
  {
    name: "invitations.listForAccount",
    call: () => api.invitations.listForAccount(ID),
    method: "GET",
    path: `/bank-accounts/${ID}/invitations/`,
  },
  {
    name: "invitations.send",
    call: () => api.invitations.send(ID, "friend@example.com"),
    method: "POST",
    path: `/bank-accounts/${ID}/invite/`,
    body: { invitee_email: "friend@example.com" },
  },
  {
    name: "invitations.cancel",
    call: () => api.invitations.cancel(ID, "tok123"),
    method: "POST",
    path: `/bank-accounts/${ID}/invitations/tok123/cancel/`,
  },
  {
    name: "invitations.listMine",
    call: () => api.invitations.listMine(),
    method: "GET",
    path: "/users/me/invitations/",
  },
  // notifications.ts
  {
    name: "notifications.listPreferences",
    call: () => api.notifications.listPreferences(),
    method: "GET",
    path: "/notification-preferences/",
  },
  {
    name: "notifications.updatePreference",
    call: () => api.notifications.updatePreference("budget overdrawn", "digest"),
    method: "PATCH",
    path: "/notification-preferences/budget%20overdrawn/",
    body: { delivery_mode: "digest" },
  },
  {
    name: "notifications.listChannels",
    call: () => api.notifications.listChannels(),
    method: "GET",
    path: "/channel-preferences/",
  },
  {
    name: "notifications.updateChannel",
    call: () => api.notifications.updateChannel("email", "weekly_friday"),
    method: "PATCH",
    path: "/channel-preferences/email/",
    body: { digest_frequency: "weekly_friday" },
  },
  // transactionCategories.ts
  {
    name: "transactionCategories.list",
    call: () => api.transactionCategories.list({ group: "Food", archived: false }),
    method: "GET",
    path: "/transaction-categories/?group=Food&archived=false",
  },
  {
    name: "transactionCategories.get",
    call: () => api.transactionCategories.get(ID),
    method: "GET",
    path: `/transaction-categories/${ID}/`,
  },
  // transactions.ts
  {
    name: "transactions.list",
    call: () => api.transactions.list({ bank_account: ID, pending: false, search: "coffee shop" }),
    method: "GET",
    path: `/transactions/?bank_account=${ID}&pending=false&search=coffee+shop`,
  },
  {
    name: "pages.fetchPage",
    call: () => api.pages.fetchPage(`https://mibudge.example/api/v1/transactions/?page=2`),
    method: "GET",
    path: "/transactions/?page=2",
  },
  {
    name: "transactions.get",
    call: () => api.transactions.get(ID),
    method: "GET",
    path: `/transactions/${ID}/`,
  },
  {
    name: "transactions.update",
    call: () => api.transactions.update(ID, { description: "Lunch", memo: "with Sam" }),
    method: "PATCH",
    path: `/transactions/${ID}/`,
    body: { description: "Lunch", memo: "with Sam" },
  },
  {
    name: "transactions.uploadAttachment",
    call: () => api.transactions.uploadAttachment(ID, "image", new File(["png"], "receipt.png")),
    method: "PATCH",
    path: `/transactions/${ID}/`,
    body: { image: "receipt.png" },
  },
  {
    name: "transactions.split",
    call: () => api.transactions.split(ID, { [ID]: "5.00", other: "7.34" }),
    method: "POST",
    path: `/transactions/${ID}/splits/`,
    body: { splits: { [ID]: "5.00", other: "7.34" } },
  },
  // users.ts
  { name: "users.me", call: () => api.users.me(), method: "GET", path: "/users/me/" },
  {
    name: "users.updateMe",
    call: () => api.users.updateMe({ timezone: "Europe/Paris" }),
    method: "PATCH",
    path: "/users/me/",
    body: { timezone: "Europe/Paris" },
  },
  {
    name: "users.changePassword",
    call: () =>
      api.users.changePassword({ current_password: "a", new_password: "b", confirm_password: "b" }),
    method: "POST",
    path: "/users/me/change-password/",
    body: { current_password: "a", new_password: "b", confirm_password: "b" },
  },
  {
    name: "users.changeEmail",
    call: () => api.users.changeEmail("new@example.com"),
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

  // GIVEN: a resource endpoint function
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
