//
// `useRefreshOnReturn`: signal the invalidation store when the page
// comes back -- shown again after being hidden, or the network back
// online -- so the shown data is refetched.  Feature composable
// (shell).
//
// The store decides from how long the page was hidden whether it may
// have missed a change (`STALE_AFTER_MS`); coming back online always
// refreshes.  Called once, from `main.ts`.
//

// app imports
//
import { usePageReturn } from "@/composables/usePageReturn";
import { useInvalidationStore } from "@/stores/invalidation";

////////////////////////////////////////////////////////////////////////
//
export function useRefreshOnReturn(): () => void {
  const invalidation = useInvalidationStore();
  return usePageReturn({
    shown: (hiddenMs) => void invalidation.pageShown(hiddenMs),
    online: () => void invalidation.invalidate(),
  });
}
