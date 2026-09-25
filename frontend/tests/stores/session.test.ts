//
// Session store tests: sign-in, the shared user load, profile update,
// the timezone fallback, and sign-out resetting every store.  The
// 401 → refresh → retry cycle is in `tests/api/http.test.ts`.
//

// 3rd party imports
//
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

// app imports
//
import { useSessionStore } from "@/stores/session";
import { userFromDto } from "@/models/user";
import { respondOnce401, TEST_TOKEN, withAuth } from "../helpers";
import { makeUser } from "../mocks/factories";
import { LOGIN_TOKEN } from "../mocks/handlers";
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
    const session = useSessionStore();

    await session.login("alice@example.com", "hunter2");
    await session.loadUser();

    expect(session.accessToken).toBe(LOGIN_TOKEN);
    expect(session.isAuthenticated).toBe(true);
    expect(session.user).toEqual(userFromDto(me));
    const [tokenReq] = await requestsTo("POST", "/api/token/");
    expect(tokenReq.body).toEqual({
      email: "alice@example.com",
      password: "hunter2",
    });
    const [meReq] = await requestsTo("GET", "/api/v1/users/me/");
    expect(meReq.headers.authorization).toBe(`Bearer ${LOGIN_TOKEN}`);
  });

  // GIVEN: wrong credentials
  // WHEN:  the user logs in
  // THEN:  login rejects and the store stays unauthenticated
  //
  it("rejects and stays logged out on bad credentials", async () => {
    respondOnce401("/api/token/", "post");
    const session = useSessionStore();

    await expect(
      session.login("alice@example.com", "wrong"),
    ).rejects.toMatchObject({
      status: 401,
    });
    expect(session.isAuthenticated).toBe(false);
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
    const session = withAuth(TEST_TOKEN, user);

    expect(await session.loadUser()).toEqual(userFromDto(user));
    expect(await requestsTo("GET", "/api/v1/users/me/")).toHaveLength(0);
  });

  // GIVEN: no cached user
  // WHEN:  several callers load the user at once
  // THEN:  one `/users/me/` request serves them all
  //
  it("shares one request between concurrent callers", async () => {
    const session = withAuth();
    session.user = null;

    const [a, b] = await Promise.all([session.loadUser(), session.loadUser()]);

    expect(a).toEqual(b);
    expect(await requestsTo("GET", "/api/v1/users/me/")).toHaveLength(1);
  });

  // GIVEN: a `/users/me/` request that fails
  // WHEN:  `loadUser(true)` is called
  // THEN:  it resolves to null instead of throwing
  //
  it("resolves to null when the profile cannot be loaded", async () => {
    const session = withAuth();
    server.use(
      http.get(
        "/api/v1/users/me/",
        () => new HttpResponse(null, { status: 500 }),
      ),
    );

    expect(await session.loadUser(true)).toBeNull();
  });

  // GIVEN: a user load in flight
  // WHEN:  the session is signed out before it answers
  // THEN:  the late answer does not sign the user back in
  //
  it("ignores a load that finishes after sign-out", async () => {
    const session = withAuth();
    session.user = null;
    const pending = session.loadUser();

    session.logout();
    await pending;

    expect(session.user).toBeNull();
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("updateProfile", () => {
  // GIVEN: a signed-in user
  // WHEN:  their timezone is updated
  // THEN:  the PATCH is sent and the session's user and timezone follow
  //
  it("saves and applies the profile", async () => {
    const session = withAuth();

    await session.updateProfile({ timezone: "Asia/Tokyo" });

    const [req] = await requestsTo("PATCH", "/api/v1/users/me/");
    expect(req.body).toEqual({ timezone: "Asia/Tokyo" });
    expect(session.timezone).toBe("Asia/Tokyo");
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
    expect(useSessionStore().timezone).toBe("UTC");
  });

  // GIVEN: a loaded user with a profile timezone
  // WHEN:  the store's timezone is read
  // THEN:  it is the profile timezone
  //
  it("uses the user's profile timezone", () => {
    const session = withAuth(TEST_TOKEN, makeUser({ timezone: "Asia/Tokyo" }));
    expect(session.timezone).toBe("Asia/Tokyo");
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("logout", () => {
  // GIVEN: a logged-in store
  // WHEN:  the user signs out
  // THEN:  the token and user are dropped and it reports unauthenticated
  //
  it("drops the token and the user", () => {
    const session = withAuth();
    session.logout();
    expect(session.accessToken).toBeNull();
    expect(session.user).toBeNull();
    expect(session.isAuthenticated).toBe(false);
  });

  // GIVEN: a refresh cookie the server no longer accepts
  // WHEN:  a refresh is attempted
  // THEN:  it resolves false and the session is empty
  //
  it("renewToken clears the session when the refresh fails", async () => {
    const session = withAuth();
    respondOnce401("/api/token/refresh/", "post");

    expect(await session.renewToken()).toBe(false);
    expect(session.accessToken).toBeNull();
    expect(session.user).toBeNull();
  });
});
