//
// `useMergedSearch` tests: local matches at once, older server matches
// merged in after the delay, and answers for an old scope dropped.
//

// 3rd party imports
//
import { flushPromises } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ref } from "vue";

// app imports
//
import { useMergedSearch } from "@/composables/useMergedSearch";
import { withSetup } from "../helpers";

afterEach(() => {
  vi.useRealTimers();
});

////////////////////////////////////////////////////////////////////////
//
// A search over `loaded` whose server search calls `answer` (by default
// finding nothing).  Returns the search and the fetch mock.
//
function mountSearch(options: {
  loaded: string[];
  answer?: (query: string) => Promise<string[]>;
  scope?: () => string | null;
  refine?: (items: readonly string[]) => string[];
}) {
  const fetchMatches = vi.fn(options.answer ?? (async () => []));
  const { result, wrapper } = withSetup(() =>
    useMergedSearch<string>({
      items: () => options.loaded,
      text: (s) => s,
      id: (s) => s,
      scope: options.scope ?? (() => "account"),
      fetchMatches,
      refine: options.refine,
      delayMs: 300,
    }),
  );
  return { search: result, fetchMatches, wrapper };
}

////////////////////////////////////////////////////////////////////////
//
describe("useMergedSearch", () => {
  // GIVEN: loaded rows, and a server that also knows older matches
  // WHEN:  a query is typed and the delay passes
  // THEN:  the local matches come first, then the server's matches
  //        that are not already shown and that pass `refine`
  //
  it("merges older server matches after the local ones", async () => {
    vi.useFakeTimers();
    const { search, fetchMatches } = mountSearch({
      loaded: ["Kettle Cafe", "Hardware"],
      answer: async () => ["Kettle Cafe", "Old Kettle", "Pending Kettle"],
      refine: (items) => items.filter((s) => !s.startsWith("Pending")),
    });

    search.query.value = "kettle";
    await vi.advanceTimersByTimeAsync(300);
    await flushPromises();

    expect(fetchMatches).toHaveBeenCalledExactlyOnceWith("kettle");
    expect(search.results.value).toEqual(["Kettle Cafe", "Old Kettle"]);
  });

  // GIVEN: a server search in flight for one scope
  // WHEN:  the scope changes before it answers
  // THEN:  its answer is dropped
  //
  it("drops an answer for an old scope", async () => {
    vi.useFakeTimers();
    const scope = ref("account A");
    let release!: (matches: string[]) => void;
    const { search } = mountSearch({
      loaded: [],
      scope: () => scope.value,
      answer: () => new Promise((resolve) => (release = resolve)),
    });
    search.query.value = "kettle";
    await vi.advanceTimersByTimeAsync(300);

    scope.value = "account B";
    await flushPromises();
    release(["From account A"]);
    await flushPromises();

    expect(search.results.value).toEqual([]);
  });

  // GIVEN: no scope (e.g. no account selected)
  // WHEN:  a query is typed and the delay passes
  // THEN:  the server is not asked
  //
  it("skips the server search without a scope", async () => {
    vi.useFakeTimers();
    const { search, fetchMatches } = mountSearch({
      loaded: ["Kettle Cafe"],
      scope: () => null,
    });

    search.query.value = "kettle";
    await vi.advanceTimersByTimeAsync(300);

    expect(fetchMatches).not.toHaveBeenCalled();
    expect(search.results.value).toEqual(["Kettle Cafe"]);
  });
});
