//
// Auth store tests: login, the 401 → refresh → retry cycle, the
// single-flight refresh, and the timezone fallback.
//

// 3rd party imports
//
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

// app imports
//
import { AuthError } from "@/api/client";
import { useAuthStore } from "@/stores/auth";
import { expire, respondOnce401, TEST_TOKEN, withAuth } from "../helpers";
import { makeUser } from "../mocks/factories";
import { LOGIN_TOKEN, REFRESHED_TOKEN } from "../mocks/handlers";
import { requestsTo, server } from "../mocks/server";

////////////////////////////////////////////////////////////////////////
//
describe("login", () => {
  // GIVEN: valid credentials
  // WHEN:  the user logs in and the user profile is loaded
  // THEN:  the access token from `POST /api/token/` is held in memory
  //  AND:  `/users/me/` is fetched with that token and cached as `user`
  //
  it("stores the access token and loads the user with it", async () => {
    const me = makeUser({ username: "alice", timezone: "Europe/Paris" });
    server.use(http.get("/api/v1/users/me/", () => HttpResponse.json(me)));
    const auth = useAuthStore();

    await auth.login("alice@example.com", "hunter2");
    await auth.loadUser();

    expect(auth.accessToken).toBe(LOGIN_TOKEN);
    expect(auth.isAuthenticated).toBe(true);
    expect(auth.user).toEqual(me);
    const [tokenReq] = await requestsTo("POST", "/api/token/");
    expect(tokenReq.body).toEqual({ email: "alice@example.com", password: "hunter2" });
    const [meReq] = await requestsTo("GET", "/api/v1/users/me/");
    expect(meReq.headers.authorization).toBe(`Bearer ${LOGIN_TOKEN}`);
  });

  // GIVEN: wrong credentials
  // WHEN:  the user logs in
  // THEN:  login rejects and the store stays unauthenticated
  //
  it("rejects and stays logged out on bad credentials", async () => {
    respondOnce401("/api/token/", "post");
    const auth = useAuthStore();

    await expect(auth.login("alice@example.com", "wrong")).rejects.toMatchObject({ status: 401 });
    expect(auth.isAuthenticated).toBe(false);
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("request", () => {
  // GIVEN: an access token the server no longer accepts
  // WHEN:  an authenticated request gets 401
  // THEN:  the store refreshes once and retries the request with the
  //        new token
  //  AND:  the retry's response is returned to the caller
  //
  it("refreshes once on 401 and retries with the new token", async () => {
    const auth = withAuth();
    expire(TEST_TOKEN);

    const page = await auth.request<{ count: number }>("/budgets/");

    expect(page.count).toBe(1);
    expect(auth.accessToken).toBe(REFRESHED_TOKEN);
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
  //  AND:  the store is cleared (no token, no user)
  //
  it("rejects with AuthError and clears the store when refresh fails", async () => {
    const auth = withAuth();
    expire(TEST_TOKEN);
    respondOnce401("/api/token/refresh/", "post");

    await expect(auth.request("/budgets/")).rejects.toBeInstanceOf(AuthError);
    expect(auth.accessToken).toBeNull();
    expect(auth.user).toBeNull();
  });

  // GIVEN: a request that fails for a reason other than authentication
  // WHEN:  the server answers 500
  // THEN:  the error propagates unchanged and no refresh is attempted
  //
  it("propagates non-401 errors without refreshing", async () => {
    const auth = withAuth();
    server.use(http.get("/api/v1/budgets/", () => new HttpResponse("boom", { status: 500 })));

    await expect(auth.request("/budgets/")).rejects.toMatchObject({ status: 500 });
    expect(await requestsTo("POST", "/api/token/refresh/")).toHaveLength(0);
    expect(auth.accessToken).toBe(TEST_TOKEN);
  });

  // GIVEN: three requests in flight whose access token has expired
  // WHEN:  each receives 401 and asks the auth store to refresh
  // THEN:  exactly one refresh is sent to the server
  //  AND:  every original request is retried with the new token and resolves
  //  AND:  the user stays logged in
  //
  it("shares one refresh across concurrent 401s", async () => {
    const user = makeUser();
    const auth = withAuth(TEST_TOKEN, user);
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
          : HttpResponse.json({ detail: "Token is blacklisted" }, { status: 401 });
      }),
    );

    const results = await Promise.all([
      auth.request<{ count: number }>("/budgets/"),
      auth.request<{ count: number }>("/transactions/"),
      auth.request<{ count: number }>("/allocations/"),
    ]);

    expect(await requestsTo("POST", "/api/token/refresh/")).toHaveLength(1);
    expect(results.map((r) => r.count)).toEqual([1, 1, 1]);
    for (const path of ["/api/v1/budgets/", "/api/v1/transactions/", "/api/v1/allocations/"]) {
      const reqs = await requestsTo("GET", path);
      expect(reqs.at(-1)?.headers.authorization).toBe(`Bearer ${REFRESHED_TOKEN}`);
    }
    expect(auth.accessToken).toBe(REFRESHED_TOKEN);
    expect(auth.user).toEqual(user);
  });

  // GIVEN: a refresh that has completed
  // WHEN:  a later 401 triggers another refresh
  // THEN:  a new refresh POST is sent rather than reusing the finished one
  //
  it("starts a fresh refresh after the previous one settles", async () => {
    const auth = useAuthStore();

    await auth.refresh();
    await auth.refresh();

    expect(await requestsTo("POST", "/api/token/refresh/")).toHaveLength(2);
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("loadUser", () => {
  // GIVEN: a cached user
  // WHEN:  `loadUser()` is called without `force`
  // THEN:  the cached user is returned without a request
  //
  it("returns the cached user without refetching", async () => {
    const user = makeUser();
    const auth = withAuth(TEST_TOKEN, user);

    expect(await auth.loadUser()).toEqual(user);
    expect(await requestsTo("GET", "/api/v1/users/me/")).toHaveLength(0);
  });

  // GIVEN: a `/users/me/` request that fails
  // WHEN:  `loadUser(true)` is called
  // THEN:  it resolves to null instead of throwing
  //
  it("resolves to null when the profile cannot be loaded", async () => {
    const auth = withAuth();
    server.use(http.get("/api/v1/users/me/", () => new HttpResponse(null, { status: 500 })));

    expect(await auth.loadUser(true)).toBeNull();
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("timezone", () => {
  // GIVEN: no loaded user
  // WHEN:  the store's timezone is read
  // THEN:  it falls back to "UTC"
  //
  it("falls back to UTC when user is null", () => {
    expect(useAuthStore().timezone).toBe("UTC");
  });

  // GIVEN: a loaded user with a profile timezone
  // WHEN:  the store's timezone is read
  // THEN:  it is the profile timezone
  //
  it("uses the user's profile timezone", () => {
    const auth = withAuth(TEST_TOKEN, makeUser({ timezone: "Asia/Tokyo" }));
    expect(auth.timezone).toBe("Asia/Tokyo");
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("clear", () => {
  // GIVEN: a logged-in store
  // WHEN:  it is cleared
  // THEN:  the token and user are dropped and it reports unauthenticated
  //
  it("drops the token and the user", () => {
    const auth = withAuth();
    auth.clear();
    expect(auth.accessToken).toBeNull();
    expect(auth.user).toBeNull();
    expect(auth.isAuthenticated).toBe(false);
  });
});
