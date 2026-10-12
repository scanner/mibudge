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
function page(
  results: number[],
  next: string | null = null,
): ModelPage<number> {
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

////////////////////////////////////////////////////////////////////////
//
describe("useInfiniteList refresh", () => {
  // GIVEN: a list scrolled two pages deep
  // WHEN:  it refreshes after a new row arrived on the server
  // THEN:  it fetches the loaded rows plus headroom and swaps them in
  //        at once: the new row on top, every loaded row still there
  //  AND:  `loading` never turns on, so the page does not blank
  //
  it("refreshes as deep as the list was scrolled", async () => {
    let rows = [1, 2, 3];
    const sizes: (number | undefined)[] = [];
    // The server's default page here is one row.
    const { result } = withSetup(() =>
      useInfiniteList(
        async (pageSize) => {
          sizes.push(pageSize);
          const n = pageSize ?? 1;
          return page(rows.slice(0, n), n < rows.length ? "p2" : null);
        },
        async () => page(rows.slice(1, 2), "p3"),
      ),
    );
    await result.reload();
    await result.loadMore();
    expect(result.items.value).toEqual([1, 2]);

    rows = [0, 1, 2, 3];
    const refresh = result.refresh();
    expect(result.loading.value).toBe(false);
    await refresh;

    expect.soft(result.items.value, "rows").toEqual([0, 1, 2, 3]);
    expect.soft(sizes, "page sizes").toEqual([undefined, 52]);
  });

  // GIVEN: more rows loaded than the server's largest page holds
  // WHEN:  the list refreshes
  // THEN:  it asks for the largest page and follows `next` until the
  //        loaded depth is covered
  //
  it("follows next past the largest page", async () => {
    const rows = Array.from({ length: 800 }, (_, i) => i);
    const sizes: (number | undefined)[] = [];
    const { result } = withSetup(() =>
      useInfiniteList(
        async (pageSize) => {
          sizes.push(pageSize);
          return page(rows.slice(0, pageSize ?? 800), "p2");
        },
        async () => page(rows.slice(500), null),
      ),
    );
    await result.reload();

    await result.refresh();

    expect.soft(sizes.at(-1), "largest page").toBe(500);
    expect.soft(result.items.value.length, "rows").toBe(800);
  });

  // GIVEN: loaded rows
  // WHEN:  a refresh fails
  // THEN:  the rows stay and no error is shown
  //
  it("keeps the rows when it fails", async () => {
    let fail = false;
    const { result } = withSetup(() =>
      useInfiniteList(
        async () => {
          if (fail) throw new Error("offline");
          return page([1]);
        },
        async () => page([]),
      ),
    );
    await result.reload();

    fail = true;
    await result.refresh();

    expect([result.items.value, result.error.value]).toEqual([[1], null]);
  });

  // GIVEN: a next page in flight
  // WHEN:  the list refreshes and the late page then arrives
  // THEN:  the late page is dropped (the refresh covered its rows) and
  //        `loadingMore` is off
  //
  it("drops a page that was loading when it refreshed", async () => {
    let releaseP2!: (p: ModelPage<number>) => void;
    const { result } = withSetup(() =>
      useInfiniteList(
        async () => page([1], "p2"),
        () => new Promise<ModelPage<number>>((res) => (releaseP2 = res)),
      ),
    );
    await result.reload();
    const more = result.loadMore();

    const refresh = result.refresh();
    expect(result.loadingMore.value).toBe(false);
    await refresh;
    releaseP2(page([99]));
    await more;

    expect(result.items.value).toEqual([1]);
  });
});
