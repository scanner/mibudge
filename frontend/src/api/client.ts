//
// Thin fetch wrapper for the mibudge DRF API.
//
// Uses the browser's native fetch for simplicity and fewer dependencies,
// in keeping with the Vue ecosystem approach.  Token injection and 401
// handling are the caller's responsibility (see stores/auth.ts).
//

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
// Base fetch wrapper.  All API calls go through here.
//
// NOTE: Does NOT handle 401 retry — that lives in the auth store so that
//       token refresh logic is co-located with token storage.
//
export async function apiFetch<T>(
  url: string,
  token: string | null,
  options: RequestInit = {},
): Promise<T> {
  const { headers: extraHeaders, ...rest } = options;

  const response = await fetch(`/api${url}`, {
    ...rest,
    headers: {
      "Content-Type": "application/json",
      // Only set Authorization when a token is present — unauthenticated
      // endpoints (e.g. /api/token/refresh/) must not send a stale token.
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...extraHeaders,
    },
  });

  if (!response.ok) {
    const body = await response.text().catch(() => "");
    throw new ApiError(response.status, body);
  }

  // Return null for 204 No Content rather than trying to parse an empty body.
  if (response.status === 204) return null as T;

  return response.json() as Promise<T>;
}
