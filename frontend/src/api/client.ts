//
// Thin fetch wrapper for the mibudge DRF API.
//
// Two base paths are in play:
//   - /api/v1/      — versioned resource endpoints (budgets, transactions, ...)
//   - /api/         — cross-version auth endpoints (token, token/refresh)
//
// See `task-mibudge-importers` in tasks.org for the decision to version
// resource endpoints while keeping JWT auth flat.  Call sites use
// `apiFetch` for resources (default, prepends /api/v1) and
// `authFetch` for auth (prepends /api).  Token injection and 401
// handling are the caller's responsibility — see stores/auth.ts.
//

////////////////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////
//
export const API_V1_BASE = "/api/v1";
export const API_AUTH_BASE = "/api";

////////////////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////
//
export class ApiError extends Error {
  readonly status: number;
  readonly body: string;

  constructor(status: number, body: string) {
    super(`HTTP ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

////////////////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////
//
export class AuthError extends Error {
  constructor(message = "Session expired") {
    super(message);
    this.name = "AuthError";
  }
}

////////////////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////
//
// Internal helper: fetch against a specific base and return typed JSON.
//
// NOTE: Does NOT handle 401 retry — that lives in the auth store so
//       token refresh logic is co-located with token storage.
//
async function requestAt<T>(
  base: string,
  url: string,
  token: string | null,
  options: RequestInit = {},
): Promise<T> {
  const { headers: extraHeaders, body, ...rest } = options;

  // Only serialise JSON bodies automatically; pass through FormData and
  // other body types untouched so multipart uploads work.
  const isJsonBody = body !== undefined && body !== null && !(body instanceof FormData);
  const finalBody = isJsonBody && typeof body !== "string" ? JSON.stringify(body) : body;

  const response = await fetch(`${base}${url}`, {
    ...rest,
    body: finalBody as BodyInit | null | undefined,
    headers: {
      ...(isJsonBody ? { "Content-Type": "application/json" } : {}),
      // Only set Authorization when a token is present — unauthenticated
      // endpoints (e.g. /api/token/refresh/) must not send a stale token.
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...extraHeaders,
    },
  });

  if (!response.ok) {
    const errBody = await response.text().catch(() => "");
    throw new ApiError(response.status, errBody);
  }

  // Parse the body only when there is content to parse.  Some endpoints
  // return 201 or other 2xx codes with an empty body; calling response.json()
  // on an empty body throws in WebKit ("The string did not match the expected
  // pattern.") so we guard on the Content-Length / Content-Type headers
  // before attempting JSON parsing.
  const contentLength = response.headers.get("Content-Length");
  const contentType = response.headers.get("Content-Type") ?? "";
  if (
    contentLength === "0" ||
    response.status === 204 ||
    !contentType.includes("application/json")
  ) {
    return null as T;
  }

  return response.json() as Promise<T>;
}

////////////////////////////////////////////////////////////////////////
//
// Fetch a versioned resource endpoint.  `url` is a path under /api/v1/,
// e.g. "/budgets/" or "/transactions/:id/".
//
export function apiFetch<T>(
  url: string,
  token: string | null,
  options: RequestInit = {},
): Promise<T> {
  return requestAt<T>(API_V1_BASE, url, token, options);
}

////////////////////////////////////////////////////////////////////////
//
// Fetch an auth endpoint (/api/token/, /api/token/refresh/).  Kept
// separate so auth URLs don't migrate with API version bumps.
//
export function authFetch<T>(
  url: string,
  token: string | null,
  options: RequestInit = {},
): Promise<T> {
  return requestAt<T>(API_AUTH_BASE, url, token, options);
}
