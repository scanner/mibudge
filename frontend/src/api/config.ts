declare global {
  interface Window {
    __mibudge?: { adminEmail?: string };
  }
}

export const adminEmail: string = window.__mibudge?.adminEmail ?? "";
