//
// `useDebouncedAutosave` tests: the debounce, the key captured when the
// value was typed, cancellation on key change and unmount, flush, and
// the error state.
//

// 3rd party imports
//
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { nextTick, ref } from "vue";

// app imports
//
import { useDebouncedAutosave } from "@/composables/useDebouncedAutosave";
import { withSetup } from "../helpers";

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

////////////////////////////////////////////////////////////////////////
//
describe("useDebouncedAutosave", () => {
  // GIVEN: several edits in quick succession
  // WHEN:  typing stops for the delay
  // THEN:  one save runs, with the last value and the current key
  //
  it("saves the last value once after the delay", async () => {
    const save = vi.fn(async () => undefined);
    const { result } = withSetup(() => useDebouncedAutosave(() => "tx1", save, { delayMs: 800 }));

    result.schedule("a");
    result.schedule("ab");
    expect(result.pending.value).toBe(true);
    await vi.advanceTimersByTimeAsync(800);

    expect(save).toHaveBeenCalledOnce();
    expect(save).toHaveBeenCalledWith("tx1", "ab");
    expect(result.pending.value).toBe(false);
  });

  // GIVEN: a pending save for record 1
  // WHEN:  the key changes to record 2 before the delay elapses
  // THEN:  the pending save is cancelled; nothing is written to either
  //
  it("cancels on key change", async () => {
    const key = ref("tx1");
    const save = vi.fn(async () => undefined);
    const { result } = withSetup(() => useDebouncedAutosave(() => key.value, save));

    result.schedule("text for tx1");
    key.value = "tx2";
    await nextTick();
    await vi.advanceTimersByTimeAsync(1000);

    expect(save).not.toHaveBeenCalled();
    expect(result.pending.value).toBe(false);
  });

  // GIVEN: a pending save
  // WHEN:  the component unmounts
  // THEN:  the save never runs
  //
  it("cancels on unmount", async () => {
    const save = vi.fn(async () => undefined);
    const { result, wrapper } = withSetup(() => useDebouncedAutosave(() => "tx1", save));

    result.schedule("x");
    wrapper.unmount();
    await vi.advanceTimersByTimeAsync(1000);

    expect(save).not.toHaveBeenCalled();
  });

  // GIVEN: a pending save
  // WHEN:  it is flushed (e.g. on blur), and then the save fails
  // THEN:  it runs at once; a failure is recorded as `error`
  //
  it("flushes now and records failures", async () => {
    const save = vi.fn(async () => {
      throw new Error("down");
    });
    const { result } = withSetup(() =>
      useDebouncedAutosave(() => "tx1", save, { errorMessage: "Not saved." }),
    );

    result.schedule("x");
    await result.flush();

    expect(save).toHaveBeenCalledWith("tx1", "x");
    expect(result.error.value).toBe("Not saved.");
    expect(result.saving.value).toBe(false);
    await result.flush();
    expect(save).toHaveBeenCalledOnce();
    result.schedule("y");
    result.cancel();
    await vi.advanceTimersByTimeAsync(1000);
    expect(save).toHaveBeenCalledOnce();
  });

  // GIVEN: a failed save for record 1
  // WHEN:  the key changes to record 2
  // THEN:  the error clears; record 1's failure is not shown on record 2
  //
  it("clears the error on key change", async () => {
    const key = ref("tx1");
    const save = vi.fn(async () => {
      throw new Error("down");
    });
    const { result } = withSetup(() => useDebouncedAutosave(() => key.value, save));

    result.schedule("x");
    await result.flush();
    expect(result.error.value).not.toBeNull();
    key.value = "tx2";
    await nextTick();

    expect(result.error.value).toBeNull();
  });

  // GIVEN: a save for record 1 in flight
  // WHEN:  the key changes to record 2, then the save fails
  // THEN:  no error is recorded for record 2
  //
  it("ignores a failure that lands after the key changed", async () => {
    const key = ref("tx1");
    let fail!: (err: Error) => void;
    const save = vi.fn(() => new Promise<void>((_resolve, reject) => (fail = reject)));
    const { result } = withSetup(() => useDebouncedAutosave(() => key.value, save));

    result.schedule("x");
    const flushed = result.flush();
    key.value = "tx2";
    await nextTick();
    fail(new Error("down"));
    await flushed;

    expect(result.error.value).toBeNull();
  });
});
