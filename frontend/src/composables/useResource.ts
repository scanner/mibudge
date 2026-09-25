//
// `useResource`: load data for a reactive key and reload whenever the
// key changes.  Composables layer.
//
// `key` is a getter (a route param, the active account id); while it
// returns `null` / `undefined` the resource is reset and nothing loads.
// Built on `useAsync`, so a response for an old key never overwrites
// the data for the current one.
//

// 3rd party imports
//
import { watch } from "vue";

// app imports
//
import type { UseAsync, UseAsyncOptions } from "@/composables/useAsync";
import { useAsync } from "@/composables/useAsync";

////////////////////////////////////////////////////////////////////////
//
export interface UseResource<T> extends Omit<UseAsync<T, []>, "run"> {
  // Load again for the current key.
  reload: () => Promise<T | undefined>;
}

////////////////////////////////////////////////////////////////////////
//
export function useResource<K, T>(
  key: () => K | null | undefined,
  loader: (key: K) => Promise<T>,
  options: UseAsyncOptions<T> = {},
): UseResource<T> {
  const state = useAsync((k: K) => loader(k), options);

  function reload(): Promise<T | undefined> {
    const k = key();
    if (k === null || k === undefined) {
      state.reset();
      return Promise.resolve(undefined);
    }
    return state.run(k);
  }

  watch(key, () => void reload(), { immediate: true });

  return {
    data: state.data,
    error: state.error,
    loading: state.loading,
    reset: state.reset,
    reload,
  };
}
