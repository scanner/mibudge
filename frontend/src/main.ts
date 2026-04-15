//
// SPA entry point.
//
// Order matters:
//   1. Create the app
//   2. Install Pinia (stores must be available before any component setup runs)
//   3. Attempt a silent refresh via the httpOnly refresh cookie so returning
//      users skip the login screen on cold boot
//   4. Install Vue Router (its `beforeEach` guard reads the auth store)
//   5. Mount
//

// 3rd party imports
//
import { createApp } from "vue";
import { createPinia } from "pinia";

// app imports
//
import App from "./App.vue";
import router from "./router";
import { useAuthStore } from "./stores/auth";
import "./style.css";

////////////////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////
//
async function bootstrap() {
  const app = createApp(App);
  app.use(createPinia());

  // Silent refresh: if the browser still holds a valid refresh cookie,
  // the SPA becomes authenticated before the first router guard runs
  // and the user lands directly on their intended route.  A failure
  // here is expected (cold boot with no session) and leaves the store
  // unauthenticated; the router guard will bounce the user to /login/.
  await useAuthStore().refresh();

  app.use(router);
  app.mount("#app");
}

bootstrap();
