//
// `useInfiniteList` tests: first page, appending pages, and dropping a
// page that belongs to an earlier reload.
//

// 3rd party imports
//
import { flushPromises } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

// app imports
//
import { useInfiniteList } from "@/composables/useInfiniteList";
import type { ModelPage } from "@/models/page";
import { withSetup } from "../helpers";

////////////////////////////////////////////////////////////////////////
//
function page(results: number[], next: string | null = null): ModelPage<number> {
  return { count: results.length, next, results };
}

////////////////////////////////////////////////////////////////////////
//
describe("useInfiniteList", () => {
  // GIVEN: a list with two further pages
  // WHEN:  it loads and then loads more (the sentinel is on screen)
  // THEN:  pages are appended until there is no `next`
  //
  it("loads the first page and appends the rest", async () => {
    const pages: Record<string, ModelPage<number>> = {
      p2: page([2], "p3"),
      p3: page([3]),
    };
    const { result } = withSetup(() =>
      useInfiniteList(
        async () => page([1], "p2"),
        async (url) => pages[url],
      ),
    );

    await result.reload();
    expect(result.items.value).toEqual([1]);
    expect(result.hasMore.value).toBe(true);

    // With a sentinel element near the viewport, one `loadMore` keeps
    // going until the pages run out.
    result.sentinel.value = document.createElement("div");
    await result.loadMore();

    expect(result.items.value).toEqual([1, 2, 3]);
    expect(result.hasMore.value).toBe(false);
    expect(result.loadingMore.value).toBe(false);
  });

  // GIVEN: a reload in flight for account A
  // WHEN:  a reload for account B starts and finishes first
  // THEN:  A's late page is dropped and B's items remain
  //
  it("drops a page from an earlier reload", async () => {
    let account = "A";
    let releaseA!: (p: ModelPage<number>) => void;
    const { result } = withSetup(() =>
      useInfiniteList(
        () =>
          account === "A"
            ? new Promise<ModelPage<number>>((res) => (releaseA = res))
            : Promise.resolve(page([20])),
        async () => page([]),
      ),
    );

    const first = result.reload();
    account = "B";
    await result.reload();
    releaseA(page([10]));
    await first;

    expect(result.items.value).toEqual([20]);
    expect(result.loading.value).toBe(false);
  });

  // GIVEN: a first page that fails
  // WHEN:  the list loads
  // THEN:  the error is recorded and the list is empty
  //  AND:  clear() empties the list without loading
  //
  it("records an error and clears", async () => {
    const { result } = withSetup(() =>
      useInfiniteList(
        async () => {
          throw new Error("boom");
        },
        async () => page([]),
        { errorMessage: "Failed to load." },
      ),
    );

    await result.reload();
    expect(result.error.value).toBe("Failed to load.");
    result.clear();
    await flushPromises();
    expect([result.items.value, result.error.value]).toEqual([[], null]);
  });
});
