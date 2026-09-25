//
// `useShellConfig` tests: settings the Django shell passes in
// `window.__mibudge`.
//

// 3rd party imports
//
import { afterEach, describe, expect, it } from "vitest";

// app imports
//
import { useShellConfig } from "@/composables/useShellConfig";

afterEach(() => {
  window.__mibudge = { adminEmail: "admin@example.com" };
});

////////////////////////////////////////////////////////////////////////
//
describe("useShellConfig", () => {
  // GIVEN: the Django shell template sets `window.__mibudge.adminEmail`
  // WHEN:  the shell config is read
  // THEN:  `adminEmail` holds that address
  //
  it("reads the address from window.__mibudge", () => {
    expect(useShellConfig().adminEmail).toBe("admin@example.com");
  });

  // GIVEN: a page without the global
  // WHEN:  the shell config is read
  // THEN:  it defaults to an empty address
  //
  it("defaults when the global is missing", () => {
    window.__mibudge = undefined;
    expect(useShellConfig().adminEmail).toBe("");
  });
});
