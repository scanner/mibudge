//
// `useAsync`: run an async function and track its result, error and
// loading state, keeping only the latest call's outcome.  Composables
// layer.
//
// Each `run()` starts a new generation; when an older call settles
// after a newer one started, its result and error are dropped.  That
// is the stale-response guard for anything re-run on input change
// (an account switch, a route param change).
//
// Returns readonly state refs (`data`, `error`, `loading`) and the
// actions `run`, `refresh` and `reset`.  `error` is a message for the
// UI (see `describeError`); `run` resolves to the result, or
// `undefined` when the call failed or was superseded.
//
// `refresh` reloads in the background: the shown `data` stays and
// `loading` stays false while it runs.  Its result replaces `data` and
// clears `error`; a failure leaves both as they were, except a 404:
// the record is gone, so `data` is reset and `error` set, as when the
// first load finds nothing.  It joins the
// same generations as `run`, so a `run` started later wins, and it does
// nothing while a `run` is in flight (that load is already current).
//

// 3rd party imports
//
import { computed, ref, shallowRef } from "vue";
import type { ComputedRef } from "vue";

// app imports
//
import { ApiError, describeError } from "@/api/errors";

////////////////////////////////////////////////////////////////////////
//
export interface UseAsyncOptions<T> {
  initial?: T;
  // Message for errors that carry none of their own (see
  // `describeError`).
  errorMessage?: string;
}

export interface UseAsync<T, A extends unknown[]> {
  data: ComputedRef<T | undefined>;
  error: ComputedRef<string | null>;
  loading: ComputedRef<boolean>;
  run: (...args: A) => Promise<T | undefined>;
  refresh: (...args: A) => Promise<T | undefined>;
  reset: () => void;
}

////////////////////////////////////////////////////////////////////////
//
export function useAsync<T, A extends unknown[] = []>(
  fn: (...args: A) => Promise<T>,
  options: UseAsyncOptions<T> = {},
): UseAsync<T, A> {
  const data = shallowRef<T | undefined>(options.initial);
  const error = ref<string | null>(null);
  const loading = ref(false);
  let generation = 0;

  async function run(...args: A): Promise<T | undefined> {
    const current = ++generation;
    loading.value = true;
    error.value = null;
    try {
      const result = await fn(...args);
      if (current !== generation) return undefined;
      data.value = result;
      return result;
    } catch (err) {
      if (current === generation)
        error.value = describeError(err, options.errorMessage);
      return undefined;
    } finally {
      if (current === generation) loading.value = false;
    }
  }

  async function refresh(...args: A): Promise<T | undefined> {
    if (loading.value) return undefined;
    const current = ++generation;
    try {
      const result = await fn(...args);
      if (current !== generation) return undefined;
      data.value = result;
      error.value = null;
      return result;
    } catch (err) {
      if (
        current === generation &&
        err instanceof ApiError &&
        err.status === 404
      ) {
        data.value = options.initial;
        error.value = describeError(err, options.errorMessage);
      }
      return undefined;
    }
  }

  function reset(): void {
    generation++;
    data.value = options.initial;
    error.value = null;
    loading.value = false;
  }

  return {
    data: computed(() => data.value),
    error: computed(() => error.value),
    loading: computed(() => loading.value),
    run,
    refresh,
    reset,
  };
}
