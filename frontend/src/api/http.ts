//
// The HTTP transport: the one place the SPA calls `fetch`.  API layer:
// no Vue, Pinia or router imports -- everything session-related comes
// in through `HttpClientConfig` callbacks.
//
// `createHttpClient(config)` returns an `HttpClient` that:
//
// - resolves paths against `baseUrl` (default: the page origin);
// - encodes a request body from `json` (JSON) or `form` (multipart),
//   and a query string from `query`;
// - sends `Authorization: Bearer <token>` from `getToken()` unless the
//   request opts out with `auth: false`;
// - on 401 runs `refresh()` once -- single-flight, so concurrent 401s
//   share one refresh -- and retries the request with the new token;
//   when the refresh fails it calls `onAuthFailure` and throws
//   `AuthError`;
// - throws `ApiError` (DRF error body parsed) on any other non-2xx;
// - throws `NetworkError` when `fetch` itself rejects, except for an
//   abort, which is rethrown as is;
// - resolves to `null` for an empty or non-JSON 2xx response.
//
// `main.ts` creates the client once and wires the callbacks to the
// session store; `api/index.ts` hands it to the resource modules.
//

// app imports
//
import { ApiError, AuthError, NetworkError } from "@/api/errors";

////////////////////////////////////////////////////////////////////////
//
export type QueryValue = string | number | boolean | null | undefined;
export type Query = { [key: string]: QueryValue };

////////////////////////////////////////////////////////////////////////
//
export interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  // Body sent as JSON with `Content-Type: application/json`.
  json?: unknown;
  // Body sent as multipart; the browser sets the boundary header.
  form?: FormData;
  query?: object;
  // `false` sends no `Authorization` header and skips the 401 refresh
  // (the token endpoints themselves).
  auth?: boolean;
  signal?: AbortSignal;
}

////////////////////////////////////////////////////////////////////////
//
export interface HttpClientConfig {
  // Prefix for every path, e.g. `https://mibudge.example`.  Default
  // `""` resolves paths against the page origin.
  baseUrl?: string;
  getToken: () => string | null;
  // Obtain a new access token (e.g. POST /api/token/refresh/ with the
  // httpOnly cookie) and store it where `getToken` reads it.  Resolves
  // `true` on success; `false` or a rejection means the session is over.
  refresh: () => Promise<boolean>;
  onAuthFailure?: (err: AuthError) => void;
  fetchImpl?: typeof fetch;
}

////////////////////////////////////////////////////////////////////////
//
export interface HttpClient {
  request<T>(path: string, options?: RequestOptions): Promise<T>;
  get<T>(path: string, query?: object): Promise<T>;
  post<T>(path: string, json?: unknown): Promise<T>;
  patch<T>(path: string, json: unknown): Promise<T>;
  delete<T = null>(path: string): Promise<T>;
  // Single-flight token refresh; concurrent callers share one attempt.
  refresh(): Promise<boolean>;
}

////////////////////////////////////////////////////////////////////////
//
// `?a=1&b=true` from an object.  `undefined`, `null` and `""` are
// dropped; booleans serialise as `true` / `false`, which Django's
// boolean filters parse.  An empty result is `""` (no `?`).
//
export function toQueryString(params: object | undefined): string {
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
// Path plus query string of a URL.  DRF's pagination links are
// absolute (`https://host/api/v1/budgets/?page=2`); requesting only
// their path keeps every request on `baseUrl`.
//
export function pathOf(url: string): string {
  if (url.startsWith("/")) return url;
  const u = new URL(url);
  return u.pathname + u.search;
}

////////////////////////////////////////////////////////////////////////
//
async function parseBody<T>(response: Response): Promise<T> {
  // Some endpoints answer 2xx with an empty body; `response.json()` on
  // an empty body throws in WebKit, so check the headers first.
  const contentLength = response.headers.get("Content-Length");
  const contentType = response.headers.get("Content-Type") ?? "";
  if (
    contentLength === "0" ||
    response.status === 204 ||
    !contentType.includes("application/json")
  ) {
    return null as T;
  }
  return (await response.json()) as T;
}

////////////////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////
//
export function createHttpClient(config: HttpClientConfig): HttpClient {
  const baseUrl = config.baseUrl ?? "";
  // The global `fetch` is looked up per call, so an interceptor
  // installed after the client exists (MSW in tests) is honoured.
  const doFetch = (input: string, init: RequestInit) =>
    config.fetchImpl ? config.fetchImpl(input, init) : fetch(input, init);

  //////////////////////////////////////////////////////////////////////
  //
  // Single-flight refresh.  The backend rotates and blacklists the
  // refresh cookie on each use, so a second parallel refresh would
  // carry a blacklisted cookie, get 401, and end a session the first
  // refresh just renewed.
  //
  let inFlightRefresh: Promise<boolean> | null = null;

  function refresh(): Promise<boolean> {
    if (!inFlightRefresh) {
      inFlightRefresh = config
        .refresh()
        .catch(() => false)
        .finally(() => {
          inFlightRefresh = null;
        });
    }
    return inFlightRefresh;
  }

  //////////////////////////////////////////////////////////////////////
  //
  async function send(
    path: string,
    options: RequestOptions,
  ): Promise<Response> {
    const headers: Record<string, string> = {};
    let body: BodyInit | undefined;
    if (options.form) {
      body = options.form;
    } else if (options.json !== undefined) {
      body = JSON.stringify(options.json);
      headers["Content-Type"] = "application/json";
    }
    const token = options.auth === false ? null : config.getToken();
    if (token) headers.Authorization = `Bearer ${token}`;

    try {
      return await doFetch(`${baseUrl}${path}${toQueryString(options.query)}`, {
        method: options.method ?? "GET",
        headers,
        body,
        signal: options.signal,
        credentials: "same-origin",
      });
    } catch (err) {
      // An abort is the caller's own doing; rethrow it as is.
      if (err instanceof DOMException && err.name === "AbortError") throw err;
      throw new NetworkError(err);
    }
  }

  //////////////////////////////////////////////////////////////////////
  //
  async function request<T>(
    path: string,
    options: RequestOptions = {},
  ): Promise<T> {
    let response = await send(path, options);

    if (response.status === 401 && options.auth !== false) {
      if (!(await refresh())) {
        const err = new AuthError();
        config.onAuthFailure?.(err);
        throw err;
      }
      response = await send(path, options);
    }

    if (!response.ok) {
      const text = await response.text().catch(() => "");
      throw new ApiError(response.status, text);
    }
    return parseBody<T>(response);
  }

  return {
    request,
    get: <T>(path: string, query?: object) => request<T>(path, { query }),
    post: <T>(path: string, json?: unknown) =>
      request<T>(path, { method: "POST", json }),
    patch: <T>(path: string, json: unknown) =>
      request<T>(path, { method: "PATCH", json }),
    delete: <T = null>(path: string) => request<T>(path, { method: "DELETE" }),
    refresh,
  };
}
