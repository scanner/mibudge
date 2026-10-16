//
// `usePageReturn`: call back when the page comes back -- shown again
// after being hidden (another tab, a minimised window, a locked phone),
// or the network back after being offline.  Composables layer.
//
// `shown(hiddenMs)` receives how long the page was hidden.  The
// listeners are removed by the returned `stop()`, and with the
// enclosing effect scope when there is one.
//

// 3rd party imports
//
import { getCurrentScope, onScopeDispose } from "vue";

////////////////////////////////////////////////////////////////////////
//
export interface PageReturnHandlers {
  shown?: (hiddenMs: number) => void;
  online?: () => void;
}

////////////////////////////////////////////////////////////////////////
//
export function usePageReturn(handlers: PageReturnHandlers): () => void {
  let hiddenAt: number | null =
    document.visibilityState === "hidden" ? Date.now() : null;

  function onVisibilityChange(): void {
    if (document.visibilityState === "hidden") {
      hiddenAt ??= Date.now();
      return;
    }
    if (hiddenAt === null) return;
    const hiddenMs = Date.now() - hiddenAt;
    hiddenAt = null;
    handlers.shown?.(hiddenMs);
  }

  function onOnline(): void {
    handlers.online?.();
  }

  document.addEventListener("visibilitychange", onVisibilityChange);
  window.addEventListener("online", onOnline);

  function stop(): void {
    document.removeEventListener("visibilitychange", onVisibilityChange);
    window.removeEventListener("online", onOnline);
  }

  if (getCurrentScope()) onScopeDispose(stop);
  return stop;
}
