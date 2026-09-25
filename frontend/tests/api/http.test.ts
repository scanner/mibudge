//
// Transport tests for `src/api/http.ts` and `src/api/errors.ts`: paths,
// the auth header, body and query encoding, empty responses, DRF error
// parsing, and the 401 → single-flight refresh → retry cycle.
//
// Most tests build a client with `createHttpClient` and a token /
// refresh they control.  The last group runs the session-wired client
// from `tests/setup.ts`, the way the app runs.
//

// 3rd party imports
//
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

// app imports
//
import { api } from "@/api";
import {
  ApiError,
  AuthError,
  describeError,
  NetworkError,
  parseDrfError,
} from "@/api/errors";
import { createHttpClient, pathOf, toQueryString } from "@/api/http";
import type { HttpClientConfig } from "@/api/http";
import { useSessionStore } from "@/stores/session";
import { expire, respondOnce401, TEST_TOKEN, withAuth } from "../helpers";
import { makePage, makeUser } from "../mocks/factories";
import { REFRESHED_TOKEN } from "../mocks/handlers";
import { lastRequest, requestsTo, server } from "../mocks/server";

////////////////////////////////////////////////////////////////////////
//
function client(overrides: Partial<HttpClientConfig> = {}) {
  return createHttpClient({
    getToken: () => null,
    refresh: async () => false,
    ...overrides,
  });
}

////////////////////////////////////////////////////////////////////////
//
describe("paths", () => {
  // GIVEN: a resource call and a token call
  // WHEN:  they are sent
  // THEN:  the resource goes to `/api/v1/...` and the token endpoint to
  //        `/api/token/...`, outside the versioned tree
  //
  it("resources live under /api/v1 and token endpoints under /api", async () => {
    await api.budgets.list();
    expect((await lastRequest())?.path).toBe("/api/v1/budgets/");
    await api.auth.refreshToken();
    expect((await lastRequest())?.path).toBe("/api/token/refresh/");
  });

  // GIVEN: a client with a base URL
  // WHEN:  a path is requested
  // THEN:  the base URL is prefixed
  //
  it("prefixes baseUrl", async () => {
    await client({ baseUrl: "http://localhost" }).get("/api/v1/banks/");
    expect((await lastRequest())?.url).toBe("http://localhost/api/v1/banks/");
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("Authorization header", () => {
  // GIVEN: an access token
  // WHEN:  a request is made
  // THEN:  the request carries `Authorization: Bearer <token>`
  //
  it("is sent when there is a token", async () => {
    await client({ getToken: () => "abc123" }).get("/api/v1/budgets/");
    expect((await lastRequest())?.headers.authorization).toBe("Bearer abc123");
  });

  // GIVEN: no access token, or a request marked `auth: false`
  // WHEN:  it is made
  // THEN:  the request has no `Authorization` header at all
  //
  it("is absent when the token is null or auth is off", async () => {
    await client().get("/api/v1/budgets/");
    expect((await lastRequest())?.headers).not.toHaveProperty("authorization");
    await client({ getToken: () => "abc123" }).request("/api/token/refresh/", {
      method: "POST",
      auth: false,
    });
    expect((await lastRequest())?.headers).not.toHaveProperty("authorization");
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("request bodies and query strings", () => {
  // GIVEN: a `json` body
  // WHEN:  it is sent
  // THEN:  it is JSON-encoded with `Content-Type: application/json`
  //
  it("JSON-encodes a plain object", async () => {
    await client().post("/api/v1/budgets/", { name: "Rent", paused: false });
    const req = await lastRequest();
    expect(req?.headers["content-type"]).toBe("application/json");
    expect(req?.body).toEqual({ name: "Rent", paused: false });
  });

  // GIVEN: a `form` body
  // WHEN:  it is sent
  // THEN:  it is passed through untouched and the client sets no
  //        `Content-Type`, leaving the multipart boundary to the browser
  //
  it("passes FormData through without setting Content-Type", async () => {
    const form = new FormData();
    form.append("memo", "lunch");
    await client().request("/api/v1/transactions/x/", {
      method: "PATCH",
      form,
    });
    const req = await lastRequest();
    expect(req?.headers["content-type"]).toMatch(
      /^multipart\/form-data; boundary=/,
    );
    expect(req?.body).toEqual({ memo: "lunch" });
  });

  // GIVEN: a params object
  // WHEN:  it is turned into a query string
  // THEN:  undefined, null and empty values are dropped, booleans become
  //        "true"/"false", and an empty result yields no "?"
  //
  it.each([
    [undefined, ""],
    [{}, ""],
    [{ a: undefined, b: null, c: "" }, ""],
    [{ archived: false }, "?archived=false"],
    [
      { bank_account: "x", page: 2, pending: true },
      "?bank_account=x&page=2&pending=true",
    ],
    [{ search: "a&b c" }, "?search=a%26b+c"],
  ])("toQueryString(%j) = %j", (params, expected) => {
    expect(toQueryString(params)).toBe(expected);
  });

  // GIVEN: a request with `query`
  // WHEN:  it is sent
  // THEN:  the query string is appended to the path
  //
  it("appends the query", async () => {
    await client().get("/api/v1/budgets/", {
      archived: false,
      ordering: "name",
    });
    expect((await lastRequest())?.path).toBe(
      "/api/v1/budgets/?archived=false&ordering=name",
    );
  });

  // GIVEN: an absolute pagination link or a path
  // WHEN:  its request path is taken
  // THEN:  only the path and query string remain
  //
  it.each([
    [
      "https://mibudge.example/api/v1/budgets/?page=2",
      "/api/v1/budgets/?page=2",
    ],
    ["/api/v1/budgets/?page=3", "/api/v1/budgets/?page=3"],
  ])("pathOf(%s) = %s", (url, expected) => {
    expect(pathOf(url)).toBe(expected);
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("pagination", () => {
  // GIVEN: a first page whose `next` links to two further pages
  // WHEN:  all pages are fetched
  // THEN:  each `next` URL is requested under `/api/v1` in order
  //  AND:  the results of every page are returned in order
  //
  it("follows next links and concatenates results", async () => {
    withAuth();
    server.use(
      http.get("/api/v1/budgets/", ({ request }) => {
        const page = new URL(request.url).searchParams.get("page");
        return page === "2"
          ? HttpResponse.json(
              makePage([2], {
                next: "http://localhost/api/v1/budgets/?page=3",
              }),
            )
          : HttpResponse.json(makePage([3]));
      }),
    );
    const first = makePage([1], {
      next: "https://mibudge.example/api/v1/budgets/?page=2",
    });

    const all = await api.pages.all(first);

    expect(all).toEqual([1, 2, 3]);
    const paths = (await requestsTo("GET", "/api/v1/budgets/")).map(
      (r) => r.path,
    );
    expect(paths).toEqual([
      "/api/v1/budgets/?page=2",
      "/api/v1/budgets/?page=3",
    ]);
  });

  // GIVEN: a single page with no `next`
  // WHEN:  all pages are fetched
  // THEN:  its results are returned without any request
  //
  it("returns a single page without requesting", async () => {
    expect(await api.pages.all(makePage(["a"]))).toEqual(["a"]);
    expect(await requestsTo("GET", "/api/v1/budgets/")).toHaveLength(0);
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("empty responses", () => {
  // GIVEN: an endpoint that answers with no body
  // WHEN:  the response is 204, or a 2xx that is empty or not JSON
  // THEN:  the call resolves to `null` without a JSON parse error
  //
  it.each([
    ["204 No Content", () => new HttpResponse(null, { status: 204 })],
    [
      "201 with Content-Length 0",
      () =>
        new HttpResponse("", {
          status: 201,
          headers: { "Content-Length": "0" },
        }),
    ],
    ["200 non-JSON", () => new HttpResponse("ok", { status: 200 })],
  ])("resolves to null for %s", async (_label, respond) => {
    server.use(http.post("/api/v1/empty/", respond));
    await expect(client().post("/api/v1/empty/")).resolves.toBeNull();
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("error responses", () => {
  // GIVEN: an endpoint that answers with a non-2xx status
  // WHEN:  the request completes
  // THEN:  the call rejects with `ApiError` carrying the status and the
  //        raw response body
  //
  it.each([400, 403, 404, 409, 500])(
    "rejects with ApiError on %i",
    async (status) => {
      const body = JSON.stringify({ detail: `status ${status}` });
      server.use(
        http.get("/api/v1/budgets/", () => new HttpResponse(body, { status })),
      );

      const err = await client()
        .get("/api/v1/budgets/")
        .catch((e: unknown) => e);

      expect(err).toBeInstanceOf(ApiError);
      expect((err as ApiError).status).toBe(status);
      expect((err as ApiError).body).toBe(body);
    },
  );

  // GIVEN: a request that never gets a response (fetch itself rejects)
  // WHEN:  the request is made
  // THEN:  the call rejects with `NetworkError`, the original rejection
  //        as its `cause`
  //
  it("rejects with NetworkError when fetch fails", async () => {
    server.use(http.get("/api/v1/budgets/", () => HttpResponse.error()));

    const err = await client()
      .get("/api/v1/budgets/")
      .catch((e: unknown) => e);

    expect(err).toBeInstanceOf(NetworkError);
    expect((err as NetworkError).cause).toBeInstanceOf(TypeError);
  });

  // GIVEN: a request whose signal is aborted
  // WHEN:  fetch rejects with the abort
  // THEN:  the abort is rethrown as is, not reported as a network failure
  //
  it("passes an abort through unchanged", async () => {
    const abort = new DOMException("The operation was aborted.", "AbortError");
    const err = await client({ fetchImpl: () => Promise.reject(abort) })
      .get("/api/v1/budgets/")
      .catch((e: unknown) => e);

    expect(err).toBe(abort);
  });

  // GIVEN: a DRF error body
  // WHEN:  it is parsed into an `ApiError`
  // THEN:  `detail`, field errors (nested keys flattened) and non-field
  //        errors are separated, and `message` is the most specific one
  //
  it.each([
    [{ detail: "Not found." }, "Not found.", {}, []],
    [
      {
        name: ["This field is required."],
        non_field_errors: ["Bad combination."],
      },
      "Bad combination.",
      { name: ["This field is required."] },
      ["Bad combination."],
    ],
    [
      { splits: { abc: ["Too large."] } },
      "Too large.",
      { "splits.abc": ["Too large."] },
      [],
    ],
    [["Plain list error."], "Plain list error.", {}, ["Plain list error."]],
  ])("parses %j", (body, message, fieldErrors, nonFieldErrors) => {
    const err = new ApiError(400, JSON.stringify(body));
    expect(err.message).toBe(message);
    expect(err.fieldErrors).toEqual(fieldErrors);
    expect(err.nonFieldErrors).toEqual(nonFieldErrors);
  });

  // GIVEN: an error body that is not JSON, or empty
  // WHEN:  it is parsed
  // THEN:  there are no messages and `message` is `HTTP <status>`
  //
  it.each(["<html>oops</html>", ""])(
    "falls back to HTTP <status> for %j",
    (body) => {
      expect(parseDrfError(body)).toEqual({
        detail: null,
        fieldErrors: {},
        nonFieldErrors: [],
      });
      expect(new ApiError(502, body).message).toBe("HTTP 502");
    },
  );

  // GIVEN: anything a request can throw
  // WHEN:  it is described for the UI
  // THEN:  API errors give the server's message, or the fallback and
  //        status when the server sent none; an ended session and a
  //        network failure get their own notices, and anything else the
  //        fallback
  //
  it.each([
    [new ApiError(400, JSON.stringify({ detail: "Nope." })), "Nope."],
    [
      new ApiError(400, JSON.stringify({ amount: ["Too large."] })),
      "Too large.",
    ],
    [new ApiError(502, "<html>Bad gateway</html>"), "fallback (HTTP 502)"],
    [new ApiError(500, ""), "fallback (HTTP 500)"],
    [new AuthError(), "Your session has expired. Please sign in again."],
    [
      new NetworkError(new TypeError("Failed to fetch")),
      "Could not reach the server. Check your connection.",
    ],
    [new TypeError("Cannot read properties of undefined"), "fallback"],
    [new Error("boom"), "fallback"],
    ["weird", "fallback"],
  ])("describeError(%s)", (err, message) => {
    expect(describeError(err, "fallback")).toBe(message);
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("401 handling", () => {
  // GIVEN: a request that gets 401 and a refresh that succeeds
  // WHEN:  the request is made
  // THEN:  the client refreshes once and retries with the new token
  //
  it("refreshes and retries once", async () => {
    let token = "old";
    respondOnce401("/api/v1/budgets/", "get");
    const c = client({
      getToken: () => token,
      refresh: async () => {
        token = "new";
        return true;
      },
    });

    await c.get("/api/v1/budgets/");

    const reqs = await requestsTo("GET", "/api/v1/budgets/");
    expect(reqs.map((r) => r.headers.authorization)).toEqual([
      "Bearer old",
      "Bearer new",
    ]);
  });

  // GIVEN: a request that gets 401 and a refresh that fails or throws
  // WHEN:  the request is made
  // THEN:  it rejects with `AuthError` and `onAuthFailure` is told
  //
  it.each([
    ["fails", async () => false],
    [
      "throws",
      async () => {
        throw new Error("network");
      },
    ],
  ])("rejects with AuthError when the refresh %s", async (_label, refresh) => {
    respondOnce401("/api/v1/budgets/", "get");
    const onAuthFailure = vi.fn();

    const err = await client({ getToken: () => "t", refresh, onAuthFailure })
      .get("/api/v1/budgets/")
      .catch((e: unknown) => e);

    expect(err).toBeInstanceOf(AuthError);
    expect(onAuthFailure).toHaveBeenCalledWith(err);
  });

  // GIVEN: a request marked `auth: false` that gets 401
  // WHEN:  it is made
  // THEN:  no refresh runs and it rejects with `ApiError(401)`
  //
  it("does not refresh for auth: false requests", async () => {
    respondOnce401("/api/token/", "post");
    const refresh = vi.fn(async () => true);

    await expect(
      client({ refresh }).request("/api/token/", {
        method: "POST",
        auth: false,
      }),
    ).rejects.toMatchObject({ status: 401 });
    expect(refresh).not.toHaveBeenCalled();
  });
});

////////////////////////////////////////////////////////////////////////
//
// The client from `tests/setup.ts`, wired to the session store.
//
describe("session-wired client", () => {
  // GIVEN: an access token the server no longer accepts
  // WHEN:  an authenticated request gets 401
  // THEN:  the store refreshes once and retries the request with the
  //        new token
  //  AND:  the retry's response is returned to the caller
  //
  it("refreshes once on 401 and retries with the new token", async () => {
    const session = withAuth();
    expire(TEST_TOKEN);

    const page = await api.budgets.list();

    expect(page.count).toBe(1);
    expect(session.accessToken).toBe(REFRESHED_TOKEN);
    expect(await requestsTo("POST", "/api/token/refresh/")).toHaveLength(1);
    const budgetReqs = await requestsTo("GET", "/api/v1/budgets/");
    expect(budgetReqs.map((r) => r.headers.authorization)).toEqual([
      `Bearer ${TEST_TOKEN}`,
      `Bearer ${REFRESHED_TOKEN}`,
    ]);
  });

  // GIVEN: an expired access token and an expired refresh cookie
  // WHEN:  an authenticated request gets 401 and the refresh gets 401
  // THEN:  the request rejects with `AuthError`
  //  AND:  the session is cleared (no token, no user)
  //
  it("rejects with AuthError and clears the session when refresh fails", async () => {
    const session = withAuth();
    expire(TEST_TOKEN);
    respondOnce401("/api/token/refresh/", "post");

    await expect(api.budgets.list()).rejects.toBeInstanceOf(AuthError);
    expect(session.accessToken).toBeNull();
    expect(session.user).toBeNull();
  });

  // GIVEN: a request that fails for a reason other than authentication
  // WHEN:  the server answers 500
  // THEN:  the error propagates unchanged and no refresh is attempted
  //
  it("propagates non-401 errors without refreshing", async () => {
    const session = withAuth();
    server.use(
      http.get(
        "/api/v1/budgets/",
        () => new HttpResponse("boom", { status: 500 }),
      ),
    );

    await expect(api.budgets.list()).rejects.toMatchObject({ status: 500 });
    expect(await requestsTo("POST", "/api/token/refresh/")).toHaveLength(0);
    expect(session.accessToken).toBe(TEST_TOKEN);
  });

  // GIVEN: three requests in flight whose access token has expired
  // WHEN:  each receives 401 and asks for a refresh
  // THEN:  exactly one refresh is sent to the server
  //  AND:  every original request is retried with the new token and resolves
  //  AND:  the user stays logged in
  //
  it("shares one refresh across concurrent 401s", async () => {
    const user = makeUser();
    const session = withAuth(TEST_TOKEN, user);
    expire(TEST_TOKEN);
    // The backend rotates the refresh cookie and blacklists the old one:
    // only the first refresh POST succeeds, any later one gets 401.
    //
    let refreshes = 0;
    server.use(
      http.post("/api/token/refresh/", () => {
        refreshes += 1;
        return refreshes === 1
          ? HttpResponse.json({ access: REFRESHED_TOKEN })
          : HttpResponse.json(
              { detail: "Token is blacklisted" },
              { status: 401 },
            );
      }),
    );

    const results = await Promise.all([
      api.budgets.list(),
      api.transactions.list(),
      api.allocations.list(),
    ]);

    expect(await requestsTo("POST", "/api/token/refresh/")).toHaveLength(1);
    expect(results.map((r) => r.count)).toEqual([1, 1, 1]);
    for (const path of [
      "/api/v1/budgets/",
      "/api/v1/transactions/",
      "/api/v1/allocations/",
    ]) {
      const reqs = await requestsTo("GET", path);
      expect(reqs.at(-1)?.headers.authorization).toBe(
        `Bearer ${REFRESHED_TOKEN}`,
      );
    }
    expect(session.accessToken).toBe(REFRESHED_TOKEN);
    expect(session.user?.username).toBe(user.username);
  });

  // GIVEN: a refresh that has completed
  // WHEN:  another refresh is requested
  // THEN:  a new refresh POST is sent rather than reusing the finished one
  //
  it("starts a fresh refresh after the previous one settles", async () => {
    const session = useSessionStore();

    await session.refresh();
    await session.refresh();

    expect(await requestsTo("POST", "/api/token/refresh/")).toHaveLength(2);
  });
});
