//
// `useShellConfig`: settings the Django shell template passes to the
// SPA in `window.__mibudge`.  Composables layer.
//
// Read when called (not at import time), so a missing global yields
// defaults instead of breaking module load.
//

////////////////////////////////////////////////////////////////////////
//
declare global {
  interface Window {
    __mibudge?: { adminEmail?: string };
  }
}

export interface ShellConfig {
  // Where "contact support" links go; empty when not configured.
  adminEmail: string;
}

////////////////////////////////////////////////////////////////////////
//
export function useShellConfig(): ShellConfig {
  const raw = typeof window !== "undefined" ? window.__mibudge : undefined;
  return { adminEmail: raw?.adminEmail ?? "" };
}
