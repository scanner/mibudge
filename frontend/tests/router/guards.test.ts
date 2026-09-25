//
// Router tests, run through the app's real route table with a memory
// history: the auth guard, the route table's completeness, the
// not-found catch-all, and the redirect when a session ends.
//

// 3rd party imports
//
import { describe, expect, it, vi } from "vitest";
import { createMemoryHistory } from "vue-router";

// app imports
//
import { api, AuthError, initApi } from "@/api";
import { createAppRouter, redirectToLogin, routes } from "@/router";
import { createSessionHttpClient, useSessionStore } from "@/stores/session";
import { expire, respondOnce401, TEST_TOKEN, withAuth } from "../helpers";

////////////////////////////////////////////////////////////////////////
//
function makeRouter() {
  return createAppRouter(createMemoryHistory("/app/"));
}

////////////////////////////////////////////////////////////////////////
//
describe("auth guard", () => {
  // GIVEN: a visitor with no access token
  // WHEN:  they navigate to a protected route
  // THEN:  they are redirected to the login view with `next` set to the
  //        route they asked for
  //
  it.each(["/", "/budgets/", "/transactions/?search=coffee"])(
    "redirects %s to login when unauthenticated",
    async (path) => {
      const router = makeRouter();
      await router.push(path);
      expect(router.currentRoute.value.path).toBe("/login/");
      expect(router.currentRoute.value.query.next).toBe(path);
    },
  );

  // GIVEN: a visitor with no access token
  // WHEN:  they navigate to a route with `meta.access: "public"`
  // THEN:  the navigation is allowed
  //
  it.each([
    "/login/",
    "/email-change/confirmed/",
    "/email-change/revoked/",
    "/email-change/error/",
  ])("allows public route %s", async (path) => {
    const router = makeRouter();
    await router.push(path);
    expect(router.currentRoute.value.path).toBe(path);
  });

  // GIVEN: a logged-in user
  // WHEN:  they navigate to a protected route
  // THEN:  the navigation is allowed
  //
  it("allows a protected route when authenticated", async () => {
    withAuth();
    const router = makeRouter();
    await router.push("/budgets/");
    expect(router.currentRoute.value.path).toBe("/budgets/");
  });

  // GIVEN: a logged-in user
  // WHEN:  they navigate to the login view
  // THEN:  they are sent to the overview instead
  //
  it("sends an authenticated user away from login", async () => {
    withAuth();
    const router = makeRouter();
    await router.push("/login/");
    expect(router.currentRoute.value.path).toBe("/");
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("route table", () => {
  // GIVEN: the app's route table
  // WHEN:  each route is inspected
  // THEN:  every route has a name and declares its access level, and
  //        every route with an `:id` passes it to the view as a prop
  //
  it.each(routes.map((r) => [r.name, r] as const))("%s is complete", (_name, route) => {
    expect(route.name).toBeTruthy();
    expect(["public", "authenticated"]).toContain(route.meta.access);
    if (route.path.includes(":id")) expect("props" in route && route.props).toBe(true);
  });

  // GIVEN: a path no route matches
  // WHEN:  a visitor, signed in or not, navigates to it
  // THEN:  the not-found route renders, keeping the path
  //
  it.each([false, true])(
    "renders not-found for unknown paths (signed in: %s)",
    async (signedIn) => {
      if (signedIn) withAuth();
      const router = makeRouter();
      await router.push("/no/such/page/");
      expect(router.currentRoute.value.name).toBe("not-found");
      expect(router.currentRoute.value.path).toBe("/no/such/page/");
    },
  );

  // GIVEN: a named route with an id
  // WHEN:  it is resolved
  // THEN:  it produces the path Django and old links use
  //
  it("resolves named routes to their paths", () => {
    const router = makeRouter();
    expect(router.resolve({ name: "budget-detail", params: { id: "abc" } }).path).toBe(
      "/budgets/abc/",
    );
    expect(router.resolve({ name: "bank-account-detail", params: { id: "x" } }).path).toBe(
      "/account/bank-accounts/x/",
    );
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("session end", () => {
  // GIVEN: a signed-in user on a protected page whose session has
  //        expired on the server (access token and refresh cookie)
  // WHEN:  any API request fails its refresh
  // THEN:  every store is reset
  //  AND:  the user is sent to the login page with the page as `next`
  //
  it("redirects to login with a return path", async () => {
    withAuth();
    const router = makeRouter();
    await router.push("/budgets/?tab=paused");
    initApi(createSessionHttpClient({ onAuthFailure: () => void redirectToLogin(router) }));
    expire(TEST_TOKEN);
    respondOnce401("/api/token/refresh/", "post");

    await expect(api.budgets.list()).rejects.toBeInstanceOf(AuthError);

    await vi.waitFor(() => expect(router.currentRoute.value.path).toBe("/login/"));
    expect(router.currentRoute.value.query.next).toBe("/budgets/?tab=paused");
    expect(useSessionStore().isAuthenticated).toBe(false);
  });

  // GIVEN: a visitor on a public page
  // WHEN:  the session-end redirect runs
  // THEN:  they stay where they are
  //
  it("leaves public pages alone", async () => {
    const router = makeRouter();
    await router.push("/email-change/confirmed/");
    await redirectToLogin(router);
    expect(router.currentRoute.value.path).toBe("/email-change/confirmed/");
  });
});
