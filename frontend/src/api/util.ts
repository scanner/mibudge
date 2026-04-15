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
