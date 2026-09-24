//
// Auth fixtures: seed the auth store, and make the mock API reject a
// token so the 401 → refresh → retry flow runs.
//

// 3rd party imports
//
import { http, HttpResponse } from "msw";

// app imports
//
import { useAuthStore } from "@/stores/auth";
import type { User } from "@/types/api";
import { makeUser } from "../mocks/factories";
import { server } from "../mocks/server";

////////////////////////////////////////////////////////////////////////
//
export const TEST_TOKEN = "test-access-token";

////////////////////////////////////////////////////////////////////////
//
// Put the active Pinia's auth store into the logged-in state: an access
// token in memory and a loaded user.  Returns the store.
//
export function withAuth(token: string = TEST_TOKEN, user: User = makeUser()) {
  const auth = useAuthStore();
  auth.accessToken = token;
  auth.user = user;
  return auth;
}

////////////////////////////////////////////////////////////////////////
//
function unauthorized() {
  return HttpResponse.json(
    { detail: "Given token not valid for any token type", code: "token_not_valid" },
    { status: 401 },
  );
}

////////////////////////////////////////////////////////////////////////
//
// Make every `/api/v1/` request that carries `Bearer <token>` get 401,
// the way the backend answers an expired access token.  Requests with
// any other token fall through to the next matching handler.
//
export function expire(token: string = TEST_TOKEN): void {
  server.use(
    http.all("/api/v1/*", ({ request }) => {
      if (request.headers.get("Authorization") === `Bearer ${token}`) return unauthorized();
      return undefined;
    }),
  );
}

////////////////////////////////////////////////////////////////////////
//
// Answer the next request to `path` (any method by default) with 401;
// later requests reach the normal handler.  `path` is the full URL
// path, e.g. `/api/v1/budgets/` or `/api/token/refresh/`.
//
export function respondOnce401(
  path: string,
  method: "all" | "get" | "post" | "patch" | "delete" = "all",
): void {
  server.use(http[method](path, () => unauthorized(), { once: true }));
}
