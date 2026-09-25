//
// Search composable tests: `useFuzzySearch` (debounced substring
// matching) and `useFindShortcut` (Cmd/Ctrl-F and Escape).
//

// 3rd party imports
//
import { afterEach, describe, expect, it, vi } from "vitest";
import { h, nextTick, ref } from "vue";

// app imports
//
import { useFindShortcut } from "@/composables/useFindShortcut";
import { useFuzzySearch } from "@/composables/useFuzzySearch";
import { useModal } from "@/composables/useModal";
import { withSetup } from "../helpers";

afterEach(() => {
  vi.useRealTimers();
});

////////////////////////////////////////////////////////////////////////
//
describe("useFuzzySearch", () => {
  // GIVEN: a list of names
  // WHEN:  a query is typed and the debounce elapses
  // THEN:  the results are the case-insensitive substring matches
  //  AND:  results are null while the query is blank
  //
  it("matches after the debounce", async () => {
    vi.useFakeTimers();
    const items = ref(["Rent", "Groceries", "Gifts"]);
    const search = useFuzzySearch(
      () => items.value,
      (s) => s,
    );
    expect(search.results.value).toBeNull();

    search.query.value = "gr";
    await nextTick();
    expect(search.results.value).toBeNull();
    vi.advanceTimersByTime(150);

    expect(search.results.value).toEqual(["Groceries"]);
    expect(search.appliedQuery.value).toBe("gr");
  });

  // GIVEN: an active search
  // WHEN:  the list changes
  // THEN:  the results follow the new list
  //
  it("recomputes when the list changes", async () => {
    const items = ref(["Rent"]);
    const search = useFuzzySearch(
      () => items.value,
      (s) => s,
      { initialQuery: "gi" },
    );
    expect(search.results.value).toEqual([]);
    items.value = ["Rent", "Gifts"];
    expect(search.results.value).toEqual(["Gifts"]);
  });

  // GIVEN: an active search
  // WHEN:  the query is cleared, or blanked by typing
  // THEN:  the results are null at once
  //
  it("clears immediately", async () => {
    const search = useFuzzySearch(
      () => ["a"],
      (s) => s,
      { initialQuery: "a" },
    );
    search.clear();
    expect([search.query.value, search.results.value]).toEqual(["", null]);
    search.query.value = "   ";
    await nextTick();
    expect(search.results.value).toBeNull();
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("useFindShortcut", () => {
  function press(key: string, init: KeyboardEventInit = {}) {
    window.dispatchEvent(
      new KeyboardEvent("keydown", { key, cancelable: true, ...init }),
    );
  }

  // GIVEN: a page with a closed search bar
  // WHEN:  Cmd-F is pressed, then Escape
  // THEN:  the bar opens with the input focused, then closes and runs
  //        `onClose`
  //
  it("opens on Cmd-F and closes on Escape", async () => {
    const input = ref<HTMLInputElement | null>(null);
    const onClose = vi.fn();
    const { result } = withSetup(
      () => useFindShortcut({ input, onClose }),
      () => h("input", { ref: input }),
    );

    press("f", { metaKey: true });
    await nextTick();
    expect(result.open.value).toBe(true);
    expect(document.activeElement).toBe(input.value);

    press("Escape");
    expect(result.open.value).toBe(false);
    expect(onClose).toHaveBeenCalledOnce();
  });

  // GIVEN: an open search bar
  // WHEN:  it is toggled twice, and hidden when already closed
  // THEN:  it closes, reopens, and hiding a closed bar does nothing
  //
  it("toggles", () => {
    const onClose = vi.fn();
    const { result } = withSetup(() =>
      useFindShortcut({ input: ref(null), onClose, initiallyOpen: true }),
    );
    result.toggle();
    expect(result.open.value).toBe(false);
    result.hide();
    expect(onClose).toHaveBeenCalledOnce();
    result.toggle();
    expect(result.open.value).toBe(true);
  });

  // GIVEN: an open search bar and an open modal
  // WHEN:  Escape is pressed
  // THEN:  the search bar stays open (the modal owns the keyboard)
  //
  it("ignores shortcuts while a modal is open", async () => {
    const { result } = withSetup(() =>
      useFindShortcut({ input: ref(null), initiallyOpen: true }),
    );
    withSetup(() => useModal(() => true, vi.fn()));
    await nextTick();

    press("Escape");
    press("f", { ctrlKey: true });

    expect(result.open.value).toBe(true);
  });
});
