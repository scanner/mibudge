//
// `useAsync` / `useResource` tests: result, error and loading state,
// the stale-response guard, and reloading on key change.
//

// 3rd party imports
//
import { flushPromises } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import { nextTick, ref } from "vue";

// app imports
//
import { ApiError } from "@/api/errors";
import { useAsync } from "@/composables/useAsync";
import { useResource } from "@/composables/useResource";

////////////////////////////////////////////////////////////////////////
//
// A promise the test settles by hand.
//
function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

////////////////////////////////////////////////////////////////////////
//
describe("useAsync", () => {
  // GIVEN: an async function
  // WHEN:  it runs and resolves
  // THEN:  loading is true while it runs, then data holds the result
  //
  it("tracks loading and data", async () => {
    const d = deferred<number>();
    const state = useAsync(() => d.promise);

    const run = state.run();
    expect(state.loading.value).toBe(true);
    d.resolve(42);

    expect(await run).toBe(42);
    expect(state.data.value).toBe(42);
    expect(state.loading.value).toBe(false);
    expect(state.error.value).toBeNull();
  });

  // GIVEN: a call that fails with an API error, and one with an
  //        unknown error
  // WHEN:  it runs
  // THEN:  `error` holds the server's message, or the fallback
  //
  it("records a UI message on failure", async () => {
    const state = useAsync(
      async (kind: string) => {
        if (kind === "api")
          throw new ApiError(400, JSON.stringify({ detail: "Nope." }));
        throw new Error("boom");
      },
      { errorMessage: "Failed to load." },
    );

    expect(await state.run("api")).toBeUndefined();
    expect(state.error.value).toBe("Nope.");
    await state.run("other");
    expect(state.error.value).toBe("Failed to load.");
  });

  // GIVEN: a first call still in flight
  // WHEN:  a second call starts and settles first
  // THEN:  the first call's late result is ignored
  //
  it("drops a stale response", async () => {
    const first = deferred<string>();
    const second = deferred<string>();
    const calls = [first, second];
    const state = useAsync(() => calls.shift()!.promise);

    const a = state.run();
    const b = state.run();
    second.resolve("new");
    await b;
    first.resolve("old");

    expect(await a).toBeUndefined();
    expect(state.data.value).toBe("new");
    expect(state.loading.value).toBe(false);
  });

  // GIVEN: a call in flight
  // WHEN:  the state is reset
  // THEN:  the data returns to the initial value and the call's result
  //        is ignored
  //
  it("reset discards in-flight results", async () => {
    const d = deferred<number>();
    const state = useAsync(() => d.promise, { initial: 0 });

    const run = state.run();
    state.reset();
    d.resolve(9);
    await run;

    expect(state.data.value).toBe(0);
    expect(state.loading.value).toBe(false);
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("useResource", () => {
  // GIVEN: a resource keyed by a reactive id
  // WHEN:  the id changes while the first load is still pending
  // THEN:  the resource loads the new id and the old answer is ignored
  //  AND:  a null id resets it without loading
  //
  it("follows the key and ignores stale loads", async () => {
    const id = ref<string | null>("a");
    const pending = new Map<string, ReturnType<typeof deferred<string>>>();
    const resource = useResource(
      () => id.value,
      (k: string) => {
        const d = deferred<string>();
        pending.set(k, d);
        return d.promise;
      },
    );

    id.value = "b";
    await nextTick();
    pending.get("b")!.resolve("B");
    await flushPromises();
    pending.get("a")!.resolve("A");
    await flushPromises();
    expect(resource.data.value).toBe("B");

    id.value = null;
    await nextTick();
    expect(resource.data.value).toBeUndefined();
    expect(pending.size).toBe(2);
  });

  // GIVEN: a loaded resource
  // WHEN:  it is reloaded
  // THEN:  the loader runs again for the same key
  //
  it("reloads on demand", async () => {
    let calls = 0;
    const resource = useResource(
      () => "k",
      async () => ++calls,
    );
    await flushPromises();
    await resource.reload();
    expect(resource.data.value).toBe(2);
  });
});
