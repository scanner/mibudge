//
// `useOptimistic` tests: the value shown while a change is saving, one
// request per key at a time with queued changes coalesced, the server's
// answer as the value afterwards, and the error from the final request.
//

// 3rd party imports
//
import { describe, expect, it, vi } from "vitest";
import { ref } from "vue";

// app imports
//
import { ApiError } from "@/api/errors";
import { useOptimistic } from "@/composables/useOptimistic";

////////////////////////////////////////////////////////////////////////
//
// A promise the test settles by hand.
//
function deferred() {
  let resolve!: () => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<void>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

////////////////////////////////////////////////////////////////////////
//
// A server-held value per key and a `commit` whose calls the test
// settles one by one.  A resolved call writes its value into `saved`,
// the way a real commit writes the server's answer into its source.
//
function harness(initial: Record<string, string>) {
  const saved = ref<Record<string, string>>({ ...initial });
  const calls: {
    key: string;
    value: string;
    done: ReturnType<typeof deferred>;
  }[] = [];
  const commit = vi.fn(async (key: string, value: string) => {
    const done = deferred();
    calls.push({ key, value, done });
    await done.promise;
    saved.value = { ...saved.value, [key]: value };
  });
  const opt = useOptimistic((key: string) => saved.value[key], commit, {
    errorMessage: "Failed to save.",
  });
  return { saved, calls, commit, opt };
}

////////////////////////////////////////////////////////////////////////
//
describe("useOptimistic", () => {
  // GIVEN: a saved value
  // WHEN:  a change is made and the request succeeds
  // THEN:  the new value shows at once, and afterwards the value is the
  //        server's
  //
  it("shows the change at once and the server's value after", async () => {
    const { saved, calls, opt } = harness({ a: "off" });

    const set = opt.set("a", "on");
    expect(opt.value("a")).toBe("on");
    expect(opt.saving("a")).toBe(true);

    calls[0].done.resolve();
    await set;

    expect(saved.value.a).toBe("on");
    expect(opt.value("a")).toBe("on");
    expect(opt.saving("a")).toBe(false);
    expect(opt.error.value).toBeNull();
  });

  // GIVEN: a saved value
  // WHEN:  a change is made and the server refuses it
  // THEN:  the saved value shows again and the error says why
  //
  it("falls back to the saved value and reports a failure", async () => {
    const { calls, opt } = harness({ a: "off" });

    const set = opt.set("a", "on");
    calls[0].done.reject(new ApiError(400, '{"detail": "Not allowed."}'));
    await set;

    expect(opt.value("a")).toBe("off");
    expect(opt.saving("a")).toBe(false);
    expect(opt.error.value).toBe("Not allowed.");
  });

  // GIVEN: a request in flight
  // WHEN:  two more changes are made before it finishes
  // THEN:  the latest change shows; only it is sent next, after the
  //        first request finishes
  //
  it("sends one request at a time and coalesces queued changes", async () => {
    const { calls, commit, opt } = harness({ a: "off" });

    const first = opt.set("a", "digest");
    const second = opt.set("a", "immediate");
    const third = opt.set("a", "on");
    expect(commit).toHaveBeenCalledOnce();
    expect(opt.value("a")).toBe("on");

    calls[0].done.resolve();
    await vi.waitFor(() => expect(commit).toHaveBeenCalledTimes(2));
    expect(calls[1].value).toBe("on");
    expect(opt.value("a")).toBe("on");

    calls[1].done.resolve();
    await Promise.all([first, second, third]);
    expect(commit).toHaveBeenCalledTimes(2);
    expect(opt.value("a")).toBe("on");
    expect(opt.saving("a")).toBe(false);
  });

  // GIVEN: a request that will fail, with a later change queued behind it
  // WHEN:  the first request fails and the later one succeeds
  // THEN:  the later change shows, and no error is reported
  //
  it("ignores an earlier failure when a later change succeeds", async () => {
    const { calls, opt } = harness({ a: "off" });

    const first = opt.set("a", "digest");
    const second = opt.set("a", "on");
    calls[0].done.reject(new Error("boom"));
    await vi.waitFor(() => expect(calls).toHaveLength(2));
    expect(opt.value("a")).toBe("on");

    calls[1].done.resolve();
    await Promise.all([first, second]);
    expect(opt.value("a")).toBe("on");
    expect(opt.error.value).toBeNull();
  });

  // GIVEN: a change in flight
  // WHEN:  the source changes underneath it (e.g. a refetch)
  // THEN:  the pending change still shows until its request finishes
  //
  it("keeps a pending change over a refetched source", async () => {
    const { saved, calls, opt } = harness({ a: "off" });

    const set = opt.set("a", "on");
    saved.value = { a: "digest" };
    expect(opt.value("a")).toBe("on");

    calls[0].done.resolve();
    await set;
    expect(opt.value("a")).toBe("on");
  });

  // GIVEN: two keys
  // WHEN:  both change at once
  // THEN:  each key's request runs independently
  //
  it("runs different keys independently", async () => {
    const { calls, commit, opt } = harness({ a: "off", b: "off" });

    const a = opt.set("a", "on");
    const b = opt.set("b", "on");
    expect(commit).toHaveBeenCalledTimes(2);

    calls[1].done.resolve();
    await b;
    expect(opt.saving("a")).toBe(true);
    expect(opt.saving("b")).toBe(false);

    calls[0].done.resolve();
    await a;
    expect(opt.value("a")).toBe("on");
  });

  // GIVEN: an error from an earlier change
  // WHEN:  a new change is made
  // THEN:  the error clears
  //
  it("clears the error on the next change", async () => {
    const { calls, opt } = harness({ a: "off" });

    const failed = opt.set("a", "on");
    calls[0].done.reject(new Error("boom"));
    await failed;
    expect(opt.error.value).toBe("Failed to save.");

    const next = opt.set("a", "on");
    expect(opt.error.value).toBeNull();
    calls[1].done.resolve();
    await next;
  });
});
