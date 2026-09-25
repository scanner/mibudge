//
// Store reset registry.  Store layer.
//
// `resetPlugin` (installed on every Pinia) records each store as it is
// created; `resetAllStores(pinia)` calls every recorded store's
// `reset()` action.  Signing out goes through it, so no cached data
// survives into the next user's session.  Every store in `stores/`
// defines `reset()` (checked by `tests/stores/reset.test.ts`).
//
// `createSessionGuard()` keeps a request that started before a reset
// from writing its answer afterwards: a store bumps the guard in
// `reset()` and wraps each cache write with `whileCurrent`.
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

////////////////////////////////////////////////////////////////////////
//
export interface SessionGuard {
  // `write`, bound to the current session: a no-op once `bump()` has
  // run since it was created.
  whileCurrent<A extends unknown[]>(write: (...args: A) => void): (...args: A) => void;
  // The session a request started in, to compare with `isCurrent`.
  current(): number;
  isCurrent(started: number): boolean;
  // Start a new session (call from the store's `reset()`).
  bump(): void;
}

export function createSessionGuard(): SessionGuard {
  let session = 0;
  return {
    whileCurrent(write) {
      const started = session;
      return (...args) => {
        if (started === session) write(...args);
      };
    },
    current: () => session,
    isCurrent: (started) => started === session,
    bump: () => {
      session++;
    },
  };
}
