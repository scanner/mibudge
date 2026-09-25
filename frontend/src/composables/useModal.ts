//
// `useModal`: the behaviour every sheet and dialog shares -- body
// scroll lock, Escape to close, and focus return.  Composables layer.
// Behaviour only: the component keeps its own markup.
//
// While `open()` is true the modal:
// - holds a reference-counted lock on `document.body.style.overflow`,
//   so stacked modals share one lock and closing the top one keeps the
//   page locked until the last one closes;
// - joins a stack; Escape closes only the topmost modal;
// - remembers the element that had focus and restores it on close.
// Unmounting while open releases the lock and leaves the stack, so a
// route change never strands the page unscrollable.
//
// `isModalOpen()` tells other keyboard handlers (e.g. the find
// shortcut) that a modal owns the keyboard.
//

// 3rd party imports
//
import { computed, getCurrentScope, onScopeDispose, ref, watch } from "vue";
import type { ComputedRef } from "vue";

////////////////////////////////////////////////////////////////////////
//
// Module state shared by every modal on the page.
//
const stack = ref<symbol[]>([]);
let lockCount = 0;
let savedOverflow = "";

function lockScroll(): void {
  if (lockCount === 0) {
    savedOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
  }
  lockCount++;
}

function unlockScroll(): void {
  lockCount = Math.max(0, lockCount - 1);
  if (lockCount === 0) document.body.style.overflow = savedOverflow;
}

////////////////////////////////////////////////////////////////////////
//
export function isModalOpen(): boolean {
  return stack.value.length > 0;
}

////////////////////////////////////////////////////////////////////////
//
export interface UseModalOptions {
  // Whether this modal locks body scroll.  Default `true`.
  lockScroll?: boolean;
}

export interface UseModal {
  // True while this modal is open and on top of the stack.
  isTopmost: ComputedRef<boolean>;
}

////////////////////////////////////////////////////////////////////////
//
export function useModal(
  open: () => boolean,
  onClose: () => void,
  options: UseModalOptions = {},
): UseModal {
  const token = Symbol("modal");
  const locks = options.lockScroll ?? true;
  let active = false;
  let returnFocus: HTMLElement | null = null;

  function onKeydown(e: KeyboardEvent): void {
    if (e.key !== "Escape") return;
    if (stack.value[stack.value.length - 1] !== token) return;
    e.preventDefault();
    onClose();
  }

  function activate(): void {
    if (active) return;
    active = true;
    returnFocus =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    stack.value = [...stack.value, token];
    if (locks) lockScroll();
    window.addEventListener("keydown", onKeydown);
  }

  function deactivate(): void {
    if (!active) return;
    active = false;
    stack.value = stack.value.filter((t) => t !== token);
    if (locks) unlockScroll();
    window.removeEventListener("keydown", onKeydown);
    const target = returnFocus;
    returnFocus = null;
    if (target && target.isConnected) target.focus();
  }

  watch(open, (isOpen) => (isOpen ? activate() : deactivate()), {
    immediate: true,
  });
  if (getCurrentScope()) onScopeDispose(deactivate);

  return {
    isTopmost: computed(() => stack.value[stack.value.length - 1] === token),
  };
}
