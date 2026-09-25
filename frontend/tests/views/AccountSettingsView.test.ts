//
// AccountSettingsView tests: the password, API key, notification and
// outgoing-invitation sections against the mock REST API.
//

// 3rd party imports
//
import { flushPromises } from "@vue/test-utils";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

// app imports
//
import AccountSettingsView from "@/views/AccountSettingsView.vue";
import { mountWithApp, withAccounts, withAuth } from "../helpers";
import {
  makeApiKey,
  makeBankAccount,
  makeInvitation,
  makeNotificationPreference,
  makePage,
  makeUser,
} from "../mocks/factories";
import { requestsTo, server } from "../mocks/server";

////////////////////////////////////////////////////////////////////////
//
function button(
  wrapper: Awaited<ReturnType<typeof mountWithApp>>["wrapper"],
  text: string,
) {
  return wrapper.findAll("button").find((b) => b.text().trim() === text)!;
}

////////////////////////////////////////////////////////////////////////
//
describe("AccountSettingsView", () => {
  beforeEach(() => {
    withAuth();
    withAccounts([makeBankAccount()]);
  });

  // GIVEN: the change-password form
  // WHEN:  the server rejects the current password with a DRF 400
  // THEN:  the message appears under that field
  //
  it("shows DRF field errors from a failed password change", async () => {
    server.use(
      http.post("/api/v1/users/me/change-password/", () =>
        HttpResponse.json(
          { current_password: ["Wrong password."] },
          { status: 400 },
        ),
      ),
    );
    const { wrapper } = await mountWithApp(AccountSettingsView, {
      route: "/account/settings/",
    });

    await wrapper.get("#current-password").setValue("nope");
    await wrapper.get("form").trigger("submit");
    await flushPromises();

    expect(wrapper.text()).toContain("Wrong password.");
    expect(wrapper.text()).not.toContain("HTTP 400");
  });

  // GIVEN: an account created by invitation (no usable password)
  // WHEN:  the settings page opens
  // THEN:  the set-password link replaces the form
  //
  it("offers the set-password flow without a usable password", async () => {
    withAuth(undefined, makeUser({ has_usable_password: false }));
    const { wrapper } = await mountWithApp(AccountSettingsView, {
      route: "/account/settings/",
    });
    expect(wrapper.text()).toContain("Set a password via email");
    expect(wrapper.find("#current-password").exists()).toBe(false);
  });

  // GIVEN: the API keys section
  // WHEN:  the user creates a key, then revokes an existing one
  // THEN:  the new key's plaintext is shown once
  //  AND:  revoking asks for confirmation and marks the row revoked
  //
  it("creates and revokes API keys", async () => {
    const existing = makeApiKey({ name: "old importer" });
    server.use(
      http.get("/api/v1/users/me/api-keys/", () =>
        HttpResponse.json(makePage([existing])),
      ),
    );
    const { wrapper } = await mountWithApp(AccountSettingsView, {
      route: "/account/settings/",
    });

    await wrapper.get("#new-key-name").setValue("importer");
    await wrapper.get("#new-key-expiry").setValue("never");
    await wrapper.findAll("form")[1].trigger("submit");
    await flushPromises();
    const [create] = await requestsTo("POST", "/api/v1/users/me/api-keys/");
    expect(create.body).toEqual({ name: "importer", expiry_days: null });
    expect(wrapper.text()).toContain("mb_plaintext_key");

    await button(wrapper, "Revoke").trigger("click");
    const confirm = Array.from(document.body.querySelectorAll("button")).find(
      (b) => b.textContent?.trim() === "Revoke" && b.closest('[role="dialog"]'),
    )!;
    confirm.click();
    await flushPromises();
    expect(
      await requestsTo(
        "POST",
        `/api/v1/users/me/api-keys/${existing.uuid}/revoke/`,
      ),
    ).toHaveLength(1);
    expect(wrapper.text()).toContain("Revoked");
  });

  // GIVEN: a custom expiry that is not a number of days
  // WHEN:  the key is created
  // THEN:  it is refused before any request
  //
  it("validates a custom expiry", async () => {
    const { wrapper } = await mountWithApp(AccountSettingsView, {
      route: "/account/settings/",
    });
    await wrapper.get("#new-key-name").setValue("importer");
    await wrapper.get("#new-key-expiry").setValue("custom");
    await wrapper.get("#new-key-days").setValue("-3");
    await wrapper.findAll("form")[1].trigger("submit");
    await flushPromises();
    expect(wrapper.text()).toContain("Enter a valid number of days.");
    expect(await requestsTo("POST", "/api/v1/users/me/api-keys/")).toHaveLength(
      0,
    );
  });

  // GIVEN: a suppressible notification kind
  // WHEN:  the user changes its delivery mode and the server refuses
  // THEN:  the choice reverts and an error is shown
  //
  it("reverts a refused delivery-mode change", async () => {
    server.use(
      http.patch(
        "/api/v1/notification-preferences/:kind/",
        () => new HttpResponse(null, { status: 500 }),
      ),
    );
    const { wrapper } = await mountWithApp(AccountSettingsView, {
      route: "/account/settings/",
    });
    await vi.waitFor(() =>
      expect(wrapper.text()).toContain("Budget overdrawn"),
    );

    const select = wrapper.findAll("select").at(-1)!;
    await select.setValue("off");
    await flushPromises();

    expect(wrapper.text()).toContain(
      "Failed to update notification preference.",
    );
    expect((select.element as HTMLSelectElement).value).toBe("immediate");
  });

  // GIVEN: a delivery-mode change whose request will fail, still in flight
  // WHEN:  the user picks another mode, then the first request fails
  // THEN:  the second choice is sent after it and shown; no error, since
  //        the server ends with the user's last choice
  //
  it("keeps the latest delivery mode when an earlier change fails", async () => {
    let releaseFirst!: () => void;
    const firstHeld = new Promise<void>((r) => (releaseFirst = r));
    let calls = 0;
    server.use(
      http.patch(
        "/api/v1/notification-preferences/:kind/",
        async ({ request, params }) => {
          const body = (await request.json()) as Record<string, unknown>;
          if (++calls === 1) {
            await firstHeld;
            return new HttpResponse(null, { status: 500 });
          }
          return HttpResponse.json(
            makeNotificationPreference({ ...body, kind: String(params.kind) }),
          );
        },
      ),
    );
    const { wrapper } = await mountWithApp(AccountSettingsView, {
      route: "/account/settings/",
    });
    await vi.waitFor(() =>
      expect(wrapper.text()).toContain("Budget overdrawn"),
    );

    const select = wrapper.findAll("select").at(-1)!;
    await select.setValue("off");
    await select.setValue("digest");
    await flushPromises();
    releaseFirst();
    await flushPromises();

    expect((select.element as HTMLSelectElement).value).toBe("digest");
    expect(wrapper.text()).not.toContain(
      "Failed to update notification preference.",
    );
    const patches = await requestsTo(
      "PATCH",
      "/api/v1/notification-preferences/budget_overdrawn/",
    );
    expect(patches.at(-1)!.body).toEqual({ delivery_mode: "digest" });
  });

  // GIVEN: the email digest selector
  // WHEN:  a new frequency is picked and the server refuses it
  // THEN:  the selector shows the saved frequency again, with the error
  //
  it("shows the saved digest frequency after a refused change", async () => {
    server.use(
      http.patch(
        "/api/v1/channel-preferences/:channel/",
        () => new HttpResponse(null, { status: 500 }),
      ),
    );
    const { wrapper } = await mountWithApp(AccountSettingsView, {
      route: "/account/settings/",
    });
    await vi.waitFor(() => expect(wrapper.text()).toContain("Email digest"));
    const select = wrapper
      .findAll("select")
      .find((s) => s.text().includes("Weekly on Friday"))!;

    await select.setValue("weekly_friday");
    await flushPromises();

    expect(wrapper.text()).toContain("Failed to save email preference.");
    expect((select.element as HTMLSelectElement).value).toBe("daily_evening");
  });

  // GIVEN: the email digest selector
  // WHEN:  a new frequency is picked
  // THEN:  the email channel is updated
  //
  it("saves the email digest frequency", async () => {
    const { wrapper } = await mountWithApp(AccountSettingsView, {
      route: "/account/settings/",
    });
    await vi.waitFor(() => expect(wrapper.text()).toContain("Email digest"));
    const select = wrapper
      .findAll("select")
      .find((s) => s.text().includes("Weekly on Friday"))!;
    await select.setValue("weekly_friday");
    await select.trigger("change");
    await flushPromises();
    const [patch] = await requestsTo(
      "PATCH",
      "/api/v1/channel-preferences/email/",
    );
    expect(patch.body).toEqual({ digest_frequency: "weekly_friday" });
  });

  // GIVEN: an outgoing invitation
  // WHEN:  the user cancels it
  // THEN:  the cancel request is sent and the row disappears
  //
  it("cancels an outgoing invitation", async () => {
    const inv = makeInvitation({ invitee_email: "friend@example.com" });
    server.use(
      http.get("/api/v1/users/me/invitations/", () => HttpResponse.json([inv])),
    );
    const { wrapper } = await mountWithApp(AccountSettingsView, {
      route: "/account/settings/",
    });
    await vi.waitFor(() =>
      expect(wrapper.text()).toContain("friend@example.com"),
    );

    // The last "Cancel" is the invitation row's (the first is the
    // password form's).
    await wrapper
      .findAll("button")
      .filter((b) => b.text().trim() === "Cancel")
      .at(-1)!
      .trigger("click");
    await flushPromises();

    expect(
      await requestsTo(
        "POST",
        `/api/v1/bank-accounts/${inv.bank_account_id}/invitations/${inv.token}/cancel/`,
      ),
    ).toHaveLength(1);
    expect(wrapper.text()).not.toContain("friend@example.com");
  });
});
