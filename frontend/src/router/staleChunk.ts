//
// Recovering from a stale bundle after a deploy.  Router layer.
//
// An open tab keeps running the bundle it loaded, and each view is a
// lazily loaded chunk whose name carries a content hash.  After a
// deploy the server no longer has the old chunks, so navigating to a
// view the tab has not loaded yet fails.  When that happens the router
// does a full page load of the route it was going to: the shell is
// always revalidated with the server, so that load runs the current
// release.
//
// Vite dispatches `vite:preloadError` on `window` with the error when a
// lazy import fails; the listener records the error (without cancelling
// the event, so the import still rejects) and the router's error hook
// reloads only for a recorded error or a browser's "module failed to
// load" message.  Each target is reloaded at most once per
// `RELOAD_WINDOW_MS`, kept in sessionStorage, so a chunk that is really
// missing fails the navigation instead of reloading in a loop.  Without
// sessionStorage there is no record of the last attempt, so it does not
// reload.
//

// 3rd party imports
//
import type { RouteLocationNormalized, Router } from "vue-router";

////////////////////////////////////////////////////////////////////////
//
export const RELOAD_WINDOW_MS = 30_000;
export const RELOAD_STORAGE_KEY = "mibudge:stale-chunk-reload";

// The messages browsers give a dynamic import whose module will not
// load: Chrome, Firefox and Safari, in that order.
//
const MODULE_LOAD_FAILED =
  /Failed to fetch dynamically imported module|error loading dynamically imported module|Importing a module script failed/i;

const preloadErrors = new WeakSet<object>();
let listening = false;

////////////////////////////////////////////////////////////////////////
//
function listenForPreloadErrors(): void {
  if (listening || typeof window === "undefined") return;
  listening = true;
  window.addEventListener("vite:preloadError", (event) => {
    const payload = (event as Event & { payload?: unknown }).payload;
    if (typeof payload === "object" && payload !== null) {
      preloadErrors.add(payload);
    }
  });
}

////////////////////////////////////////////////////////////////////////
//
// Whether a navigation error is a lazy chunk that would not load.
//
export function isChunkLoadError(error: unknown): boolean {
  if (typeof error === "object" && error !== null && preloadErrors.has(error)) {
    return true;
  }
  return error instanceof Error && MODULE_LOAD_FAILED.test(error.message);
}

////////////////////////////////////////////////////////////////////////
//
// Record a reload of `href` now, unless one was recorded within the
// window.  Returns whether the caller should reload.
//
function claimReload(href: string): boolean {
  try {
    const storage = window.sessionStorage;
    const now = Date.now();
    const last = JSON.parse(storage.getItem(RELOAD_STORAGE_KEY) ?? "null") as {
      href?: unknown;
      at?: unknown;
    } | null;
    if (
      last?.href === href &&
      typeof last.at === "number" &&
      now - last.at < RELOAD_WINDOW_MS
    ) {
      return false;
    }
    storage.setItem(RELOAD_STORAGE_KEY, JSON.stringify({ href, at: now }));
    return true;
  } catch {
    return false;
  }
}

////////////////////////////////////////////////////////////////////////
//
// Install the error hook on `router`.  `reload` does the full page load
// (`window.location.assign` in the app; tests pass a spy).
//
export function reloadOnStaleChunk(
  router: Router,
  reload: (href: string) => void,
): void {
  listenForPreloadErrors();
  router.onError((error: unknown, to: RouteLocationNormalized) => {
    if (!isChunkLoadError(error)) return;
    const href = router.resolve(to.fullPath).href;
    if (claimReload(href)) reload(href);
  });
}
