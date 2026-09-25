//
// `useDebouncedAutosave`: save a field a moment after the user stops
// typing.  Composables layer.
//
// `schedule(value)` (re)starts the timer; when it fires, `save(key,
// value)` runs with the key that was current when the value was typed,
// so an edit is only ever written to the record it was typed for.
// `flush()` saves the pending value now (bind it to `blur`); a pending
// save is also flushed when the key changes (e.g. the route moves to
// another transaction) and when the component unmounts (e.g. the
// browser's back button), so leaving a record never drops an edit.
// `cancel()` discards the pending value.
//
// `error` is the last failed save's message for the current key: it
// clears when the key changes, and a save for an earlier key that fails
// after the key changed does not set it.
//

// 3rd party imports
//
import { computed, getCurrentScope, onScopeDispose, ref, watch } from "vue";
import type { ComputedRef } from "vue";

// app imports
//
import { describeError } from "@/api/errors";

////////////////////////////////////////////////////////////////////////
//
export interface UseDebouncedAutosaveOptions {
  delayMs?: number;
  errorMessage?: string;
}

export interface UseDebouncedAutosave<V> {
  pending: ComputedRef<boolean>;
  saving: ComputedRef<boolean>;
  error: ComputedRef<string | null>;
  schedule: (value: V) => void;
  flush: () => Promise<void>;
  cancel: () => void;
}

////////////////////////////////////////////////////////////////////////
//
export function useDebouncedAutosave<K, V>(
  key: () => K,
  save: (key: K, value: V) => Promise<void>,
  options: UseDebouncedAutosaveOptions = {},
): UseDebouncedAutosave<V> {
  const delayMs = options.delayMs ?? 800;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let queued: { key: K; value: V } | null = null;
  const pending = ref(false);
  const saving = ref(false);
  const error = ref<string | null>(null);

  function cancel(): void {
    if (timer) clearTimeout(timer);
    timer = null;
    queued = null;
    pending.value = false;
  }

  async function flush(): Promise<void> {
    if (timer) clearTimeout(timer);
    timer = null;
    const job = queued;
    queued = null;
    pending.value = false;
    if (!job) return;
    saving.value = true;
    error.value = null;
    try {
      await save(job.key, job.value);
    } catch (err) {
      if (job.key === key())
        error.value = describeError(err, options.errorMessage);
    } finally {
      saving.value = false;
    }
  }

  function schedule(value: V): void {
    if (timer) clearTimeout(timer);
    queued = { key: key(), value };
    pending.value = true;
    timer = setTimeout(() => void flush(), delayMs);
  }

  watch(key, () => {
    void flush();
    error.value = null;
  });
  if (getCurrentScope()) onScopeDispose(() => void flush());

  return {
    pending: computed(() => pending.value),
    saving: computed(() => saving.value),
    error: computed(() => error.value),
    schedule,
    flush,
    cancel,
  };
}
