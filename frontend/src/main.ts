//
// SPA entry point.
//
// Order matters:
//   1. Create the app
//   2. Install Pinia (stores must be available before any component setup runs)
//   3. Initialise the auth store (reads window.__INITIAL_TOKEN__ if present)
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
const app = createApp(App);

app.use(createPinia());

// NOTE: Auth store must be initialised after Pinia is installed but
//       before the router is installed so that the very first
//       navigation guard already sees the token.
useAuthStore().init();

app.use(router);

app.mount("#app");
