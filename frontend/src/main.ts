//
// SPA entry point.
//
// Order matters:
//   1. Create the app
//   2. Install Pinia (stores must be available before any component setup runs)
//   3. Install Vue Router
//   4. Initialise the auth store (reads window.__INITIAL_TOKEN__ if present)
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
app.use(router);

// NOTE: Auth store must be initialised after Pinia is installed but before
//       mount so that the first render already has the token in state.
useAuthStore().init();

app.mount("#app");
