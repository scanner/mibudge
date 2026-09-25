//
// `useFindShortcut`: a toggleable search bar with Cmd/Ctrl-F to open
// and focus it and Escape to close it.  Composables layer.
//
// While a modal owns the keyboard (see `useModal`) the shortcuts are
// ignored, so Escape closes the modal and not the search bar behind it.
//

// 3rd party imports
//
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from "vue";
import type { ComputedRef, Ref } from "vue";

// app imports
//
import { isModalOpen } from "@/composables/useModal";

////////////////////////////////////////////////////////////////////////
//
export interface UseFindShortcutOptions {
  // The search `<input>` (a template ref), focused when the bar opens.
  input: Ref<HTMLInputElement | null>;
  // Runs when the bar closes, e.g. to clear the query.
  onClose?: () => void;
  initiallyOpen?: boolean;
}

export interface UseFindShortcut {
  open: ComputedRef<boolean>;
  show: () => void;
  hide: () => void;
  toggle: () => void;
}

////////////////////////////////////////////////////////////////////////
//
export function useFindShortcut(
  options: UseFindShortcutOptions,
): UseFindShortcut {
  const open = ref(options.initiallyOpen ?? false);

  function focus(): void {
    void nextTick(() => options.input.value?.focus());
  }

  function show(): void {
    open.value = true;
    focus();
  }

  function hide(): void {
    if (!open.value) return;
    open.value = false;
    options.onClose?.();
  }

  function toggle(): void {
    if (open.value) hide();
    else show();
  }

  function onKeydown(e: KeyboardEvent): void {
    if (isModalOpen()) return;
    if (e.key === "f" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      show();
    } else if (e.key === "Escape" && open.value) {
      hide();
    }
  }

  onMounted(() => window.addEventListener("keydown", onKeydown));
  onBeforeUnmount(() => window.removeEventListener("keydown", onKeydown));

  return { open: computed(() => open.value), show, hide, toggle };
}
