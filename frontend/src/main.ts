//
// SPA entry point: the composition root that wires the layers together.
//
// Order matters:
//   1. Create the app and a Pinia with the store-reset plugin (stores
//      must exist before any component setup runs).
//   2. Create the router, and the HTTP client wired to the session
//      store; a session that ends mid-use (refresh failed) redirects to
//      the login page with a return path.
//   3. Attempt a silent refresh via the httpOnly refresh cookie, so a
//      returning user skips the login screen, and load the user and the
//      account context (one shared `/users/me/` request).
//   4. Install the router (its guard reads the session) and mount.
//

// 3rd party imports
//
import { createPinia } from "pinia";
import { createApp } from "vue";

// app imports
//
import App from "./App.vue";
import { initApi } from "./api";
import { createAppRouter, redirectToLogin } from "./router";
import { useAccountContextStore } from "./stores/accountContext";
import { resetPlugin } from "./stores/reset";
import { createSessionHttpClient, useSessionStore } from "./stores/session";
import "./style.css";

////////////////////////////////////////////////////////////////////////
//
async function bootstrap() {
  const app = createApp(App);
  const pinia = createPinia();
  pinia.use(resetPlugin);
  app.use(pinia);

  const router = createAppRouter();
  initApi(
    createSessionHttpClient({
      onAuthFailure: () => void redirectToLogin(router),
    }),
  );

  // A failed refresh is expected on a cold boot with no session; the
  // guard then sends the visitor to the login page.
  const session = useSessionStore();
  if (await session.refresh()) {
    await Promise.all([session.loadUser(), useAccountContextStore().init()]);
  }

  app.use(router);
  app.mount("#app");
}

void bootstrap();
