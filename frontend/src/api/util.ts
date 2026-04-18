//
// Shared helpers for the per-resource API modules.
//

////////////////////////////////////////////////////////////////////////
//
// Build a querystring suffix like "?a=1&b=true" from a plain object.
// Undefined and null values are dropped; booleans serialise as
// "true"/"false" to match Django's BooleanField parsing.
//
export function qs(params: object | undefined): string {
  if (!params) return "";
  const entries: [string, string][] = [];
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    entries.push([key, String(value)]);
  }
  if (entries.length === 0) return "";
  return "?" + new URLSearchParams(entries).toString();
}

////////////////////////////////////////////////////////////////////////
//
// Exhaust a paginated endpoint, collecting all results across pages.
//
import type { Paginated } from "@/types/api";
import { useAuthStore } from "@/stores/auth";

export async function fetchAllPages<T>(firstPage: Paginated<T>): Promise<T[]> {
  const all = [...firstPage.results];
  let nextUrl = firstPage.next;
  const auth = useAuthStore();
  while (nextUrl) {
    const path = nextUrl.replace(/^.*\/api\/v1/, "");
    const page = await auth.request<Paginated<T>>(path);
    all.push(...page.results);
    nextUrl = page.next;
  }
  return all;
}
