//
// Page visibility fixture: hide or show the page as a browser does when
// the user switches tabs, and announce it with `visibilitychange`.
// The stubbed `visibilityState` is restored after each test
// (`restoreMocks`).
//

// 3rd party imports
//
import { vi } from "vitest";

////////////////////////////////////////////////////////////////////////
//
export function setPageVisibility(state: DocumentVisibilityState): void {
  vi.spyOn(document, "visibilityState", "get").mockReturnValue(state);
  document.dispatchEvent(new Event("visibilitychange"));
}
