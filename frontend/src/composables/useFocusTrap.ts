//
// `useFocusTrap`: keep keyboard focus inside a container while it is
// active.  Composables layer.
//
// When `active()` becomes true the trap moves focus into the container
// -- to its first focusable element, or to the container itself -- unless
// focus is already inside.  While active, Tab from the last focusable
// element wraps to the first and Shift+Tab from the first wraps to the
// last; a Tab from outside the container lands inside it.  BaseSheet
// passes `open && isTopmost`, so only the topmost modal traps.
//

// 3rd party imports
//
import { getCurrentScope, nextTick, onScopeDispose, watch } from "vue";
import type { Ref } from "vue";

////////////////////////////////////////////////////////////////////////
//
const FOCUSABLE = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled]):not([type='hidden'])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[tabindex]:not([tabindex='-1'])",
].join(",");

////////////////////////////////////////////////////////////////////////
//
function focusables(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE));
}

////////////////////////////////////////////////////////////////////////
//
export function useFocusTrap(
  container: Ref<HTMLElement | null>,
  active: () => boolean,
): void {
  function onKeydown(e: KeyboardEvent): void {
    const el = container.value;
    if (e.key !== "Tab" || !el || !active()) return;
    const items = focusables(el);
    const current = document.activeElement;
    if (items.length === 0) {
      e.preventDefault();
      el.focus();
      return;
    }
    const first = items[0]!;
    const last = items[items.length - 1]!;
    const outside = !el.contains(current);
    if (e.shiftKey && (outside || current === first)) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && (outside || current === last)) {
      e.preventDefault();
      first.focus();
    }
  }

  watch(
    active,
    async (on) => {
      if (!on) return;
      await nextTick();
      const el = container.value;
      if (!el || el.contains(document.activeElement)) return;
      (focusables(el)[0] ?? el).focus();
    },
    { immediate: true },
  );

  window.addEventListener("keydown", onKeydown);
  if (getCurrentScope()) {
    onScopeDispose(() => window.removeEventListener("keydown", onKeydown));
  }
}
