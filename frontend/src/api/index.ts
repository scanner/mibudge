//
// The API registry: one object with a namespace per REST resource,
// e.g. `api.budgets.list(...)`.  API layer.
//
// `initApi(http)` binds every resource module to an `HttpClient`.
// `main.ts` calls it once with the session-wired client; tests call it
// in `tests/setup.ts` and may call it again with their own client.
// `api` is the same object throughout, so modules that imported it
// before `initApi` see the bound resources.
//
// Only stores and feature composables import `api`; views and
// components never do (enforced by `tests/architecture.test.ts`).
//

// app imports
//
import type { HttpClient } from "@/api/http";
import { allocationsResource } from "@/api/resources/allocations";
import { apiKeysResource } from "@/api/resources/apiKeys";
import { authResource } from "@/api/resources/auth";
import { bankAccountsResource } from "@/api/resources/bankAccounts";
import { banksResource } from "@/api/resources/banks";
import { budgetsResource } from "@/api/resources/budgets";
import { internalTransactionsResource } from "@/api/resources/internalTransactions";
import { invitationsResource } from "@/api/resources/invitations";
import { notificationsResource } from "@/api/resources/notifications";
import { pagesResource } from "@/api/resources/pages";
import { transactionCategoriesResource } from "@/api/resources/transactionCategories";
import { transactionsResource } from "@/api/resources/transactions";
import { usersResource } from "@/api/resources/users";

////////////////////////////////////////////////////////////////////////
//
function createApi(http: HttpClient) {
  return {
    allocations: allocationsResource(http),
    apiKeys: apiKeysResource(http),
    auth: authResource(http),
    bankAccounts: bankAccountsResource(http),
    banks: banksResource(http),
    budgets: budgetsResource(http),
    internalTransactions: internalTransactionsResource(http),
    invitations: invitationsResource(http),
    notifications: notificationsResource(http),
    pages: pagesResource(http),
    transactionCategories: transactionCategoriesResource(http),
    transactions: transactionsResource(http),
    users: usersResource(http),
  };
}

export type Api = ReturnType<typeof createApi>;

////////////////////////////////////////////////////////////////////////
//
let current: HttpClient | null = null;

export const api = {} as Api;

////////////////////////////////////////////////////////////////////////
//
export function initApi(http: HttpClient): void {
  current = http;
  Object.assign(api, createApi(http));
}

////////////////////////////////////////////////////////////////////////
//
// The client `initApi` installed; the session store uses it for the
// single-flight refresh.
//
export function getHttp(): HttpClient {
  if (!current) throw new Error("API not initialised: call initApi() first");
  return current;
}

export {
  ApiError,
  AuthError,
  describeError,
  isApiError,
  NetworkError,
} from "@/api/errors";
export type { HttpClient } from "@/api/http";
