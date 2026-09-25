//
// `useFuzzySearch`: debounced substring search over a reactive list,
// with fzf ranking.  Composables layer.
//
// `query` is bound to the search input.  `results` is `null` while the
// query is blank (show the whole list), otherwise the matching items,
// best match first.  Typing is debounced; clearing applies at once.
// Results recompute when the list changes, so a reload never leaves
// stale matches on screen.
//

// 3rd party imports
//
import { Fzf } from "fzf";
import { computed, getCurrentScope, onScopeDispose, ref, watch } from "vue";
import type { ComputedRef, Ref } from "vue";

////////////////////////////////////////////////////////////////////////
//
export interface UseFuzzySearchOptions {
  debounceMs?: number;
  // Initial query, e.g. restored from a store.
  initialQuery?: string;
}

export interface UseFuzzySearch<T> {
  query: Ref<string>;
  // The query the results reflect (after the debounce), trimmed.
  appliedQuery: ComputedRef<string>;
  results: ComputedRef<T[] | null>;
  clear: () => void;
}

////////////////////////////////////////////////////////////////////////
//
export function useFuzzySearch<T>(
  items: () => readonly T[],
  selector: (item: T) => string,
  options: UseFuzzySearchOptions = {},
): UseFuzzySearch<T> {
  const debounceMs = options.debounceMs ?? 150;
  const query = ref(options.initialQuery ?? "");
  const applied = ref(query.value.trim());
  let timer: ReturnType<typeof setTimeout> | null = null;

  function cancelTimer(): void {
    if (timer) clearTimeout(timer);
    timer = null;
  }

  watch(query, (q) => {
    cancelTimer();
    const trimmed = q.trim();
    if (!trimmed) {
      applied.value = "";
      return;
    }
    timer = setTimeout(() => {
      timer = null;
      applied.value = trimmed;
    }, debounceMs);
  });

  // fzf searches `{ text, index }` entries so its selector typing sees
  // a concrete element type; matches map back to the items by index.
  //
  const results = computed<T[] | null>(() => {
    const q = applied.value;
    if (!q) return null;
    const list = items();
    const entries = list.map((item, index) => ({
      text: selector(item),
      index,
    }));
    const fzf = new Fzf(entries, {
      selector: (e) => e.text,
      casing: "case-insensitive",
      fuzzy: false,
    });
    return fzf.find(q).map((r) => list[r.item.index]);
  });

  function clear(): void {
    cancelTimer();
    query.value = "";
    applied.value = "";
  }

  if (getCurrentScope()) onScopeDispose(cancelTimer);

  return { query, appliedQuery: computed(() => applied.value), results, clear };
}
