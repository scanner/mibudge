//
// `useOptimistic`: apply a change on screen at once and save it in the
// background.  Composables layer.
//
// For a control that saves as soon as the user changes it (a toggle, a
// select), keyed by the record it edits:
//
// - `value(key)` is the change being saved, or else `source(key)`, the
//   server's value.  Bind the control to it.
// - `set(key, value)` shows `value` at once and calls `commit(key,
//   value)`, which saves it and writes the server's answer into the
//   source (a store update does this for its cache).
// - Requests for one key go one at a time, in the order the user made
//   the changes, so the server ends with the user's last choice and
//   answers reach the source in order.  Changes made while a request is
//   in flight are coalesced: only the latest is sent next.
// - When the last request for a key finishes, the pending value is
//   dropped and `value(key)` is the source again: the server's answer
//   after a success, the unchanged saved value after a failure.
// - `error(key)` is the message from the key's failed last request (an
//   earlier request's failure is superseded by the change queued after
//   it); the key's next `set` clears it.  Errors are per key, so a view
//   that moves to another record never shows the previous record's
//   failure.
//

// 3rd party imports
//
import { reactive } from "vue";

// app imports
//
import { describeError } from "@/api/errors";

////////////////////////////////////////////////////////////////////////
//
export interface UseOptimisticOptions {
  errorMessage?: string;
}

export interface UseOptimistic<K, V> {
  value: (key: K) => V;
  saving: (key: K) => boolean;
  error: (key: K) => string | null;
  set: (key: K, value: V) => Promise<void>;
}

////////////////////////////////////////////////////////////////////////
//
export function useOptimistic<K, V>(
  source: (key: K) => V,
  commit: (key: K, value: V) => Promise<void>,
  options: UseOptimisticOptions = {},
): UseOptimistic<K, V> {
  // The value shown for each key with a change in progress.
  const pending = reactive(new Map<K, V>()) as Map<K, V>;
  // Per key: the running request, and the latest change waiting for it.
  const running = new Map<K, Promise<void>>();
  const queued = new Map<K, V>();
  // The message from each key's failed last request.
  const errors = reactive(new Map<K, string>()) as Map<K, string>;

  async function drain(key: K, first: V): Promise<void> {
    let current = first;
    let failed = false;
    let failure: unknown;
    for (;;) {
      failed = false;
      try {
        await commit(key, current);
      } catch (err) {
        failed = true;
        failure = err;
      }
      if (!queued.has(key)) break;
      current = queued.get(key) as V;
      queued.delete(key);
    }
    running.delete(key);
    pending.delete(key);
    if (failed) errors.set(key, describeError(failure, options.errorMessage));
  }

  function set(key: K, value: V): Promise<void> {
    pending.set(key, value);
    errors.delete(key);
    const inFlight = running.get(key);
    if (inFlight) {
      queued.set(key, value);
      return inFlight;
    }
    const run = drain(key, value);
    running.set(key, run);
    return run;
  }

  return {
    value: (key) => (pending.has(key) ? (pending.get(key) as V) : source(key)),
    saving: (key) => pending.has(key),
    error: (key) => errors.get(key) ?? null,
    set,
  };
}
