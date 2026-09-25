//
// `useInfiniteList`: a paginated list that loads the next page when a
// sentinel element scrolls into view.  Composables layer.
//
// `reload()` fetches the first page and replaces the items; `loadMore()`
// appends the next page and keeps going while the sentinel is still
// within 200px of the viewport (a filter can leave too few rows to
// scroll).  Every `reload()` starts a new generation: a page that
// arrives for an older generation (e.g. the previous bank account) is
// dropped.
//
// `error` is a failed first page (the list is then empty);
// `loadMoreError` is a failed later page (the loaded rows stay, and the
// caller offers `loadMore()` again).
//
// Bind `sentinel` to an element after the list (`ref="sentinel"`).
//

// 3rd party imports
//
import { computed, nextTick, onBeforeUnmount, ref, shallowRef, watch } from "vue";
import type { ComputedRef, Ref } from "vue";

// app imports
//
import { describeError } from "@/api/errors";
import type { ModelPage } from "@/models/page";

////////////////////////////////////////////////////////////////////////
//
const NEAR_VIEWPORT_PX = 200;

export interface UseInfiniteListOptions {
  errorMessage?: string;
}

export interface UseInfiniteList<T> {
  items: ComputedRef<T[]>;
  hasMore: ComputedRef<boolean>;
  loading: ComputedRef<boolean>;
  loadingMore: ComputedRef<boolean>;
  error: ComputedRef<string | null>;
  loadMoreError: ComputedRef<string | null>;
  sentinel: Ref<HTMLElement | null>;
  reload: () => Promise<void>;
  loadMore: () => Promise<void>;
  // Clear the list without loading (e.g. no account selected).
  clear: () => void;
}

////////////////////////////////////////////////////////////////////////
//
export function useInfiniteList<T>(
  fetchFirst: () => Promise<ModelPage<T>>,
  fetchNext: (url: string) => Promise<ModelPage<T>>,
  options: UseInfiniteListOptions = {},
): UseInfiniteList<T> {
  const items = shallowRef<T[]>([]);
  const nextUrl = ref<string | null>(null);
  const loading = ref(false);
  const loadingMore = ref(false);
  const error = ref<string | null>(null);
  const loadMoreError = ref<string | null>(null);
  const sentinel = ref<HTMLElement | null>(null);
  let generation = 0;

  ////////////////////////////////////////////////////////////////////
  //
  function clear(): void {
    generation++;
    items.value = [];
    nextUrl.value = null;
    loading.value = false;
    loadingMore.value = false;
    error.value = null;
    loadMoreError.value = null;
  }

  async function reload(): Promise<void> {
    const current = ++generation;
    loading.value = true;
    loadingMore.value = false;
    error.value = null;
    loadMoreError.value = null;
    try {
      const page = await fetchFirst();
      if (current !== generation) return;
      items.value = page.results;
      nextUrl.value = page.next;
    } catch (err) {
      if (current === generation) {
        items.value = [];
        nextUrl.value = null;
        error.value = describeError(err, options.errorMessage);
      }
    } finally {
      if (current === generation) loading.value = false;
    }
  }

  ////////////////////////////////////////////////////////////////////
  //
  function sentinelNearViewport(): boolean {
    const el = sentinel.value;
    if (!el) return false;
    return el.getBoundingClientRect().top < window.innerHeight + NEAR_VIEWPORT_PX;
  }

  async function loadMore(): Promise<void> {
    if (!nextUrl.value || loadingMore.value || loading.value) return;
    const current = generation;
    loadingMore.value = true;
    loadMoreError.value = null;
    try {
      do {
        const page = await fetchNext(nextUrl.value!);
        if (current !== generation) return;
        items.value = [...items.value, ...page.results];
        nextUrl.value = page.next;
        await nextTick();
      } while (nextUrl.value && current === generation && sentinelNearViewport());
    } catch (err) {
      if (current === generation) loadMoreError.value = describeError(err, options.errorMessage);
    } finally {
      if (current === generation) loadingMore.value = false;
    }
  }

  ////////////////////////////////////////////////////////////////////
  //
  let observer: IntersectionObserver | null = null;

  watch(sentinel, (el, _old, onCleanup) => {
    if (!el || typeof IntersectionObserver === "undefined") return;
    observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) void loadMore();
      },
      { rootMargin: `${NEAR_VIEWPORT_PX}px` },
    );
    observer.observe(el);
    onCleanup(() => observer?.disconnect());
  });

  onBeforeUnmount(() => {
    generation++;
    observer?.disconnect();
  });

  return {
    items: computed(() => items.value),
    hasMore: computed(() => nextUrl.value !== null),
    loading: computed(() => loading.value),
    loadingMore: computed(() => loadingMore.value),
    error: computed(() => error.value),
    loadMoreError: computed(() => loadMoreError.value),
    sentinel,
    reload,
    loadMore,
    clear,
  };
}
