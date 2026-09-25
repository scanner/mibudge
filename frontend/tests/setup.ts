//
// Global test setup -- the SPA-side analogue of `conftest.py`.  Vitest
// runs this file before every test file (`setupFiles` in
// vitest.config.ts).
//
// - Sets `window.__mibudge`, which the Django shell template provides in
//   production.
// - Runs the MSW mock server for the whole file, failing any request to
//   an endpoint no handler covers, and resets per-test handler overrides
//   and the request log after each test.
// - Gives each test a fresh Pinia (with the store-reset plugin, as in
//   `main.ts`), an API registry wired to that Pinia's session store,
//   and empty web storage.
// - Unmounts every component a test mounted, so modal scroll locks and
//   window listeners never leak into the next test.
//

// 3rd party imports
//
import { enableAutoUnmount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { createApp } from "vue";
import { afterAll, afterEach, beforeAll, beforeEach } from "vitest";

// app imports
//
import { initApi } from "@/api";
import { resetPlugin } from "@/stores/reset";
import { createSessionHttpClient } from "@/stores/session";
import { clearRequestLog, server } from "./mocks/server";

////////////////////////////////////////////////////////////////////////
//
// Set at module level so it is in place before any test file's imports
// run.
//
window.__mibudge = { adminEmail: "admin@example.com" };

////////////////////////////////////////////////////////////////////////
//
beforeAll(() => {
  server.listen({ onUnhandledRequest: "error" });
});

beforeEach(() => {
  // Pinia applies plugins once it is installed in an app, so it goes
  // into a bare app here; `mountWithApp` installs it again in its own.
  //
  const pinia = createPinia();
  pinia.use(resetPlugin);
  createApp({}).use(pinia);
  setActivePinia(pinia);
  initApi(createSessionHttpClient());
  window.sessionStorage.clear();
  window.localStorage.clear();
});

enableAutoUnmount(afterEach);

afterEach(() => {
  server.resetHandlers();
  clearRequestLog();
});

afterAll(() => {
  server.close();
});
