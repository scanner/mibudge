//
// `usePullToRefresh`: pull down from the top of the page to refresh.
// Composables layer.
//
// A touch that starts with the page scrolled to the top and drags
// down sets `distance` (half the drag, at most `MAX_PULL_PX`).
// Releasing past `TRIGGER_PX` (`ready`) runs `onRefresh()`;
// `refreshing` is true until it settles.  A pull while refreshing,
// inside an open sheet or dialog, or a cancelled touch, does nothing.
// The listeners are removed with the enclosing effect scope.
//

// 3rd party imports
//
import { computed, getCurrentScope, onScopeDispose, ref } from "vue";
import type { ComputedRef } from "vue";

////////////////////////////////////////////////////////////////////////
//
export const TRIGGER_PX = 64;
const MAX_PULL_PX = 96;

export interface UsePullToRefresh {
  distance: ComputedRef<number>;
  ready: ComputedRef<boolean>;
  refreshing: ComputedRef<boolean>;
}

////////////////////////////////////////////////////////////////////////
//
export function usePullToRefresh(
  onRefresh: () => Promise<unknown>,
): UsePullToRefresh {
  const distance = ref(0);
  const refreshing = ref(false);
  let startY: number | null = null;

  function atTop(): boolean {
    return (document.scrollingElement?.scrollTop ?? window.scrollY) <= 0;
  }

  function onTouchStart(e: TouchEvent): void {
    const inDialog =
      e.target instanceof Element && !!e.target.closest('[role="dialog"]');
    startY =
      !refreshing.value && !inDialog && e.touches.length === 1 && atTop()
        ? e.touches[0].clientY
        : null;
  }

  function onTouchMove(e: TouchEvent): void {
    if (startY === null) return;
    const dy = e.touches[0].clientY - startY;
    distance.value = dy > 0 ? Math.min(dy / 2, MAX_PULL_PX) : 0;
  }

  async function onTouchEnd(): Promise<void> {
    if (startY === null) return;
    startY = null;
    const fire = distance.value >= TRIGGER_PX;
    distance.value = 0;
    if (!fire) return;
    refreshing.value = true;
    try {
      await onRefresh();
    } finally {
      refreshing.value = false;
    }
  }

  function onTouchCancel(): void {
    startY = null;
    distance.value = 0;
  }

  window.addEventListener("touchstart", onTouchStart, { passive: true });
  window.addEventListener("touchmove", onTouchMove, { passive: true });
  window.addEventListener("touchend", onTouchEnd);
  window.addEventListener("touchcancel", onTouchCancel);

  if (getCurrentScope())
    onScopeDispose(() => {
      window.removeEventListener("touchstart", onTouchStart);
      window.removeEventListener("touchmove", onTouchMove);
      window.removeEventListener("touchend", onTouchEnd);
      window.removeEventListener("touchcancel", onTouchCancel);
    });

  return {
    distance: computed(() => distance.value),
    ready: computed(() => distance.value >= TRIGGER_PX),
    refreshing: computed(() => refreshing.value),
  };
}
