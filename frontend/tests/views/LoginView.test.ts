//
// LoginView tests: the form, the auth store, the account-context store,
// the API modules and the transport working together against the mock
// REST API.
//

// 3rd party imports
//
import { flushPromises } from "@vue/test-utils";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

// app imports
//
import { useAccountContextStore } from "@/stores/accountContext";
import { useAuthStore } from "@/stores/auth";
import LoginView from "@/views/LoginView.vue";
import { mountWithApp, respondOnce401 } from "../helpers";
import { makeBankAccount, makePage, makeUser } from "../mocks/factories";
import { LOGIN_TOKEN } from "../mocks/handlers";
import { requestsTo, server } from "../mocks/server";

////////////////////////////////////////////////////////////////////////
//
async function submit(wrapper: Awaited<ReturnType<typeof mountWithApp>>["wrapper"]) {
  await wrapper.find('input[type="email"]').setValue("alice@example.com");
  await wrapper.find('input[type="password"]').setValue("hunter2");
  await wrapper.find("form").trigger("submit");
  await flushPromises();
}

////////////////////////////////////////////////////////////////////////
//
describe("LoginView", () => {
  // GIVEN: the login page reached via a redirect from `/budgets/`
  // WHEN:  the user submits valid credentials
  // THEN:  the auth store holds the access token and the user profile
  //  AND:  the account context is loaded
  //  AND:  the user is sent to the route named in `next`
  //
  it("logs in and navigates to next", async () => {
    const me = makeUser({ username: "alice" });
    const account = makeBankAccount();
    server.use(
      http.get("/api/v1/users/me/", () => HttpResponse.json(me)),
      http.get("/api/v1/bank-accounts/", () => HttpResponse.json(makePage([account]))),
    );
    const { wrapper, router } = await mountWithApp(LoginView, {
      route: "/login/?next=/budgets/",
    });

    await submit(wrapper);

    // LoginView does not await `router.replace()`, and the target route's
    // component is lazy-loaded, so poll until the navigation lands.
    //
    await vi.waitFor(() => expect(router.currentRoute.value.fullPath).toBe("/budgets/"), {
      timeout: 5000,
    });
    const auth = useAuthStore();
    expect(auth.accessToken).toBe(LOGIN_TOKEN);
    expect(auth.user).toEqual(me);
    expect(useAccountContextStore().activeBankAccountId).toBe(account.id);
    const [tokenReq] = await requestsTo("POST", "/api/token/");
    expect(tokenReq.body).toEqual({ email: "alice@example.com", password: "hunter2" });
  });

  // GIVEN: the login page with no `next`
  // WHEN:  the user logs in
  // THEN:  they land on the overview
  //
  it("navigates to the overview by default", async () => {
    const { wrapper, router } = await mountWithApp(LoginView, { route: "/login/" });

    await submit(wrapper);

    // See above: the navigation completes after the lazy route loads.
    await vi.waitFor(() => expect(router.currentRoute.value.path).toBe("/"), { timeout: 5000 });
  });

  // GIVEN: the login page
  // WHEN:  the server rejects the credentials with 401
  // THEN:  an "Incorrect email or password." alert is shown
  //  AND:  the user stays on the login page, unauthenticated
  //
  it("shows an error on 401", async () => {
    respondOnce401("/api/token/", "post");
    const { wrapper, router } = await mountWithApp(LoginView, { route: "/login/" });

    await submit(wrapper);

    expect(wrapper.get('[role="alert"]').text()).toBe("Incorrect email or password.");
    expect(useAuthStore().isAuthenticated).toBe(false);
    expect(router.currentRoute.value.path).toBe("/login/");
  });

  // GIVEN: the login page
  // WHEN:  the token endpoint fails with a server error
  // THEN:  a generic retry message is shown
  //
  it("shows a generic error on other failures", async () => {
    server.use(http.post("/api/token/", () => new HttpResponse(null, { status: 500 })));
    const { wrapper } = await mountWithApp(LoginView, { route: "/login/" });

    await submit(wrapper);

    expect(wrapper.get('[role="alert"]').text()).toBe("Unable to sign in. Please try again.");
  });
});
