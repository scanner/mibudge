//
// Composable fixture: run a composable inside a mounted host component,
// so lifecycle hooks (`onMounted`, `onScopeDispose`) run as in the app.
//

// 3rd party imports
//
import { mount } from "@vue/test-utils";
import { defineComponent, h } from "vue";

////////////////////////////////////////////////////////////////////////
//
// Mount a component whose setup calls `composable()`.  Returns its
// result and the wrapper; `wrapper.unmount()` runs the cleanup.
// `render` optionally renders template refs the composable needs.
//
export function withSetup<T>(
  composable: () => T,
  render?: () => ReturnType<typeof h>,
) {
  let result!: T;
  const Host = defineComponent({
    setup() {
      result = composable();
      return render ?? (() => null);
    },
  });
  const wrapper = mount(Host, { attachTo: document.body });
  return { result, wrapper };
}
