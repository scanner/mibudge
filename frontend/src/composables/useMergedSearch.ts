//
// `useMergedSearch`: search over a paged list -- local matches among
// the loaded rows at once, plus older matches from the server after a
// pause.  Composables layer.
//
// `results` is `null` while the query is blank, otherwise the local
// matches (best first) followed by the server's matches that are not
// already among them, each passed through `refine` (a client-side
// filter the server query does not apply).  The server is asked
// `delayMs` after the query or `scope` last changed; `scope` names
// what the server search covers (e.g. the account and filter), and
// `null` turns the server search off.  An answer for an older query or
// scope is dropped.  A failed server search is ignored: the local
// matches still show.
//

// 3rd party imports
//
import {
  computed,
  getCurrentScope,
  onScopeDispose,
  shallowRef,
  watch,
} from "vue";
import type { ComputedRef, Ref } from "vue";

// app imports
//
import { useFuzzySearch } from "@/composables/useFuzzySearch";

////////////////////////////////////////////////////////////////////////
//
export interface UseMergedSearchOptions<T> {
  // The loaded rows the local search covers.
  items: () => readonly T[];
  text: (item: T) => string;
  id: (item: T) => string;
  scope: () => string | null;
  fetchMatches: (query: string) => Promise<T[]>;
  refine?: (items: readonly T[]) => T[];
  initialQuery?: string;
  delayMs?: number;
}

export interface UseMergedSearch<T> {
  query: Ref<string>;
  results: ComputedRef<T[] | null>;
  clear: () => void;
}

////////////////////////////////////////////////////////////////////////
//
export function useMergedSearch<T>(
  options: UseMergedSearchOptions<T>,
): UseMergedSearch<T> {
  const delayMs = options.delayMs ?? 300;
  const refine = options.refine ?? ((items: readonly T[]) => [...items]);
  const local = useFuzzySearch(options.items, options.text, {
    initialQuery: options.initialQuery,
  });
  const serverMatches = shallowRef<T[]>([]);
  let timer: ReturnType<typeof setTimeout> | null = null;
  let generation = 0;

  watch(
    [() => local.query.value.trim(), options.scope],
    ([q, scope]) => {
      const current = ++generation;
      if (timer) clearTimeout(timer);
      serverMatches.value = [];
      if (!q || scope === null) return;
      timer = setTimeout(async () => {
        try {
          const matches = await options.fetchMatches(q);
          if (current === generation) serverMatches.value = matches;
        } catch {
          // Server search is best-effort; local matches still show.
        }
      }, delayMs);
    },
    { immediate: true },
  );
  if (getCurrentScope()) {
    onScopeDispose(() => {
      generation++;
      if (timer) clearTimeout(timer);
    });
  }

  const results = computed<T[] | null>(() => {
    const localResults = local.results.value;
    if (!localResults) return null;
    const seen = new Set(localResults.map(options.id));
    const extra = refine(serverMatches.value).filter(
      (item) => !seen.has(options.id(item)),
    );
    return [...localResults, ...extra];
  });

  return { query: local.query, results, clear: local.clear };
}
