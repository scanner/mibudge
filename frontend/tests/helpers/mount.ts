//
// Component mounting fixture: mount a component inside the app's real
// router (memory history, so no browser URL is touched) and a Pinia.
//

// 3rd party imports
//
import { flushPromises, mount } from "@vue/test-utils";
import type { Pinia } from "pinia";
import { getActivePinia } from "pinia";
import type { Component } from "vue";
import { createMemoryHistory } from "vue-router";

// app imports
//
import { createAppRouter } from "@/router";

////////////////////////////////////////////////////////////////////////
//
export interface MountWithAppOptions {
  // Route to navigate to before mounting, e.g. `/budgets/`.
  route?: string;
  // Pinia to install.  Defaults to the active Pinia from `tests/setup.ts`,
  // so stores seeded before mounting (e.g. by `withAuth()`) are the
  // ones the component sees.  Pass `createTestingPinia()` to stub
  // store actions.
  //
  pinia?: Pinia;
  props?: Record<string, unknown>;
}

////////////////////////////////////////////////////////////////////////
//
// Navigate the router to `route` (running the auth guard), mount the
// component, and wait for pending promises (e.g. the component's first
// API calls) to settle.  Returns the wrapper and the router.
//
export async function mountWithApp(
  component: Component,
  options: MountWithAppOptions = {},
) {
  const pinia = options.pinia ?? getActivePinia();
  if (!pinia) throw new Error("mountWithApp: no active Pinia");
  const router = createAppRouter(createMemoryHistory("/app/"));
  await router.push(options.route ?? "/");
  await router.isReady();
  const wrapper = mount(component, {
    props: options.props,
    global: { plugins: [router, pinia] },
  });
  await flushPromises();
  return { wrapper, router };
}
