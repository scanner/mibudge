//
// Default happy-path handlers for every REST endpoint the SPA calls.
//
// Paths and response shapes follow `docs/openapi.yaml`.  List endpoints
// return DRF's `{count, next, previous, results}` envelope; detail
// endpoints echo the requested id back in the object.  A test replaces
// any of these for its own duration with `server.use(...)`; see
// docs/spa/testing.md.
//
// Handlers do not check the `Authorization` header.  Tests that need a
// 401 install one with `expire()` or `respondOnce401()` from
// `tests/helpers/auth.ts`.
//

// 3rd party imports
//
import { http, HttpResponse } from "msw";
import type { JsonBodyType } from "msw";

// app imports
//
import {
  makeAllocation,
  makeApiKey,
  makeBank,
  makeBankAccount,
  makeBudget,
  makeCategory,
  makeChannelPreference,
  makeFundingRunResult,
  makeFundingSummary,
  makeInternalTransaction,
  makeInvitation,
  makeNotificationPreference,
  makePage,
  makeTransaction,
  makeUser,
} from "./factories";

////////////////////////////////////////////////////////////////////////
//
export const API = "/api/v1";

// Tokens the default auth handlers issue.  Tests compare the
// `Authorization` header in the request log against these.
//
export const LOGIN_TOKEN = "login-access-token";
export const REFRESHED_TOKEN = "refreshed-access-token";

////////////////////////////////////////////////////////////////////////
//
// Read a JSON request body, or an empty object when there is none, so
// PATCH / POST handlers can echo the submitted fields back.
//
async function jsonBody(request: Request): Promise<Record<string, unknown>> {
  const text = await request.text();
  return text ? (JSON.parse(text) as Record<string, unknown>) : {};
}

function json(body: JsonBodyType, status = 200) {
  return HttpResponse.json(body, { status });
}

function noContent() {
  return new HttpResponse(null, { status: 204 });
}

////////////////////////////////////////////////////////////////////////
//
export const handlers = [
  // Cross-version JWT endpoints (/api/token/...).
  //
  http.post("/api/token/", () => json({ access: LOGIN_TOKEN })),
  http.post("/api/token/refresh/", () => json({ access: REFRESHED_TOKEN })),

  // Users.
  //
  http.get(`${API}/users/me/`, () => json(makeUser())),
  http.patch(`${API}/users/me/`, async ({ request }) =>
    json(makeUser(await jsonBody(request))),
  ),
  http.post(`${API}/users/me/change-password/`, () => noContent()),
  http.post(`${API}/users/me/change-email/`, () => noContent()),
  http.get(`${API}/users/me/invitations/`, () => json([makeInvitation()])),

  // API keys.
  //
  http.get(`${API}/users/me/api-keys/`, () => json(makePage([makeApiKey()]))),
  http.post(`${API}/users/me/api-keys/`, async ({ request }) =>
    json(
      { ...makeApiKey(await jsonBody(request)), key: "mb_plaintext_key" },
      201,
    ),
  ),
  http.post(`${API}/users/me/api-keys/:uuid/revoke/`, ({ params }) =>
    json(
      makeApiKey({
        uuid: String(params.uuid),
        revoked_at: "2026-09-02T12:00:00Z",
      }),
    ),
  ),

  // Banks.
  //
  http.get(`${API}/banks/`, () => json(makePage([makeBank()]))),
  http.get(`${API}/banks/:id/`, ({ params }) =>
    json(makeBank({ id: String(params.id) })),
  ),

  // Bank accounts.
  //
  http.get(`${API}/bank-accounts/`, () => json(makePage([makeBankAccount()]))),
  http.post(`${API}/bank-accounts/`, async ({ request }) =>
    json(makeBankAccount(await jsonBody(request)), 201),
  ),
  http.get(`${API}/bank-accounts/:id/`, ({ params }) =>
    json(makeBankAccount({ id: String(params.id) })),
  ),
  http.patch(`${API}/bank-accounts/:id/`, async ({ params, request }) =>
    json(
      makeBankAccount({ ...(await jsonBody(request)), id: String(params.id) }),
    ),
  ),
  http.delete(`${API}/bank-accounts/:id/`, () => noContent()),
  http.get(`${API}/bank-accounts/:id/funding-summary/`, () =>
    json(makeFundingSummary()),
  ),
  http.post(`${API}/bank-accounts/:id/run-funding/`, () =>
    json(makeFundingRunResult()),
  ),
  http.get(`${API}/bank-accounts/:id/invitations/`, ({ params }) =>
    json([makeInvitation({ bank_account_id: String(params.id) })]),
  ),
  http.post(`${API}/bank-accounts/:id/invite/`, () => noContent()),
  http.post(`${API}/bank-accounts/:id/invitations/:token/cancel/`, () =>
    noContent(),
  ),

  // Budgets.
  //
  http.get(`${API}/budgets/`, () => json(makePage([makeBudget()]))),
  http.post(`${API}/budgets/`, async ({ request }) =>
    json(makeBudget(await jsonBody(request)), 201),
  ),
  http.get(`${API}/budgets/:id/`, ({ params }) =>
    json(makeBudget({ id: String(params.id) })),
  ),
  http.patch(`${API}/budgets/:id/`, async ({ params, request }) =>
    json(makeBudget({ ...(await jsonBody(request)), id: String(params.id) })),
  ),
  http.delete(`${API}/budgets/:id/`, () => noContent()),
  http.post(`${API}/budgets/:id/archive/`, ({ params }) =>
    json(makeBudget({ id: String(params.id), archived: true })),
  ),

  // Transactions and allocations.
  //
  http.get(`${API}/transactions/`, () => json(makePage([makeTransaction()]))),
  http.get(`${API}/transactions/:id/`, ({ params }) =>
    json(makeTransaction({ id: String(params.id) })),
  ),
  http.patch(`${API}/transactions/:id/`, ({ params }) =>
    json(makeTransaction({ id: String(params.id) })),
  ),
  http.post(`${API}/transactions/:id/splits/`, ({ params }) =>
    json([makeAllocation({ transaction: String(params.id) })]),
  ),
  http.get(`${API}/allocations/`, () => json(makePage([makeAllocation()]))),

  // Internal transactions.
  //
  http.get(`${API}/internal-transactions/`, () =>
    json(makePage([makeInternalTransaction()])),
  ),
  http.post(`${API}/internal-transactions/`, async ({ request }) =>
    json(makeInternalTransaction(await jsonBody(request)), 201),
  ),

  // Transaction categories.
  //
  http.get(`${API}/transaction-categories/`, () =>
    json(makePage([makeCategory()])),
  ),
  http.get(`${API}/transaction-categories/:id/`, ({ params }) =>
    json(makeCategory({ id: String(params.id) })),
  ),

  // Notification preferences.
  //
  http.get(`${API}/notification-preferences/`, () =>
    json([makeNotificationPreference()]),
  ),
  http.patch(
    `${API}/notification-preferences/:kind/`,
    async ({ params, request }) =>
      json(
        makeNotificationPreference({
          ...(await jsonBody(request)),
          kind: String(params.kind),
        }),
      ),
  ),
  http.get(`${API}/channel-preferences/`, () =>
    json([makeChannelPreference()]),
  ),
  http.patch(
    `${API}/channel-preferences/:channel/`,
    async ({ params, request }) =>
      json(
        makeChannelPreference({
          ...(await jsonBody(request)),
          channel: String(params.channel),
        }),
      ),
  ),
];
