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
// - Gives each test a fresh Pinia and empty web storage.
//

// 3rd party imports
//
import { createPinia, setActivePinia } from "pinia";
import { afterAll, afterEach, beforeAll, beforeEach } from "vitest";

// app imports
//
import { clearRequestLog, server } from "./mocks/server";

////////////////////////////////////////////////////////////////////////
//
// `api/config.ts` reads `window.__mibudge` when it is first imported,
// which happens while test files load and before any hook runs, so the
// global is set at module level here.
//
window.__mibudge = { adminEmail: "admin@example.com" };

////////////////////////////////////////////////////////////////////////
//
beforeAll(() => {
  server.listen({ onUnhandledRequest: "error" });
});

beforeEach(() => {
  setActivePinia(createPinia());
  window.sessionStorage.clear();
  window.localStorage.clear();
});

afterEach(() => {
  server.resetHandlers();
  clearRequestLog();
});

afterAll(() => {
  server.close();
});
