//
// Router auth-guard tests, run through the app's real route table with
// a memory history.
//

// 3rd party imports
//
import { describe, expect, it } from "vitest";
import { createMemoryHistory } from "vue-router";

// app imports
//
import { createAppRouter } from "@/router";
import { withAuth } from "../helpers";

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
  // WHEN:  they navigate to a route marked `meta.public`
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
