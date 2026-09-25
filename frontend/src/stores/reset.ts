//
// Store reset registry.  Store layer.
//
// `resetPlugin` (installed on every Pinia) records each store as it is
// created; `resetAllStores(pinia)` calls every recorded store's
// `reset()` action.  Signing out goes through it, so no cached data
// survives into the next user's session.  Every store in `stores/`
// defines `reset()` (checked by `tests/stores/reset.test.ts`).
//

// 3rd party imports
//
import type { Pinia, PiniaPluginContext } from "pinia";

////////////////////////////////////////////////////////////////////////
//
interface Resettable {
  reset?: () => void;
}

const created = new WeakMap<Pinia, Set<Resettable>>();

////////////////////////////////////////////////////////////////////////
//
export function resetPlugin({ pinia, store }: PiniaPluginContext): void {
  let stores = created.get(pinia);
  if (!stores) {
    stores = new Set();
    created.set(pinia, stores);
  }
  stores.add(store as unknown as Resettable);
}

////////////////////////////////////////////////////////////////////////
//
export function resetAllStores(pinia: Pinia): void {
  for (const store of created.get(pinia) ?? []) store.reset?.();
}
