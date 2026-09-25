//
// The MSW mock server and its request log.
//
// `server` intercepts every `fetch` the SPA makes and answers from the
// default handlers in `handlers.ts` (or a test's `server.use(...)`
// overrides).  `tests/setup.ts` starts it with
// `onUnhandledRequest: 'error'`, so a request to an unmocked endpoint
// fails the test.
//
// The request log records each intercepted request as
// `{method, url, path, headers, body}` from MSW's `request:start` event, in the
// order the SPA sent them.  Tests assert on it with `requestsTo()` and
// `lastRequest()`, e.g. "exactly one POST /api/token/refresh/".
//

// 3rd party imports
//
import { setupServer } from "msw/node";

// app imports
//
import { handlers } from "./handlers";

////////////////////////////////////////////////////////////////////////
//
export const server = setupServer(...handlers);

////////////////////////////////////////////////////////////////////////
//
export interface LoggedRequest {
  method: string;
  // Absolute URL, e.g. `http://localhost/api/v1/budgets/?archived=false`.
  url: string;
  // Path plus query string, e.g. `/api/v1/budgets/?archived=false`.
  path: string;
  // Header names are lower-case, e.g. `headers.authorization`.
  headers: Record<string, string>;
  // Parsed JSON for `application/json`; an object of field → value for
  // `multipart/form-data` (a `File` is recorded as its file name); raw
  // text otherwise; `undefined` when the request had no body.
  //
  body: unknown;
}

export const requestLog: LoggedRequest[] = [];

// Body parsing is asynchronous; `pending` holds the parses in progress so
// the query helpers only ever read complete entries.
//
const pending = new Set<Promise<void>>();

////////////////////////////////////////////////////////////////////////
//
async function readBody(request: Request): Promise<unknown> {
  const contentType = request.headers.get("Content-Type") ?? "";
  if (contentType.includes("multipart/form-data")) {
    const form = await request.formData();
    const out: Record<string, string> = {};
    form.forEach((value, key) => {
      out[key] = typeof value === "string" ? value : value.name;
    });
    return out;
  }
  const text = await request.text();
  if (!text) return undefined;
  return contentType.includes("application/json") ? JSON.parse(text) : text;
}

server.events.on("request:start", ({ request }) => {
  const url = new URL(request.url);
  const entry: LoggedRequest = {
    method: request.method,
    url: request.url,
    path: url.pathname + url.search,
    // happy-dom's `Headers` keeps the case the caller used; lower-case the
    // names as the Fetch spec does so lookups are stable.
    //
    headers: Object.fromEntries(
      Array.from(request.headers.entries(), ([k, v]) => [k.toLowerCase(), v]),
    ),
    body: undefined,
  };
  requestLog.push(entry);
  const parse = readBody(request.clone()).then((body) => {
    entry.body = body;
  });
  pending.add(parse);
  void parse.finally(() => pending.delete(parse));
});

////////////////////////////////////////////////////////////////////////
//
// Wait until every logged request's body has been parsed.
//
export async function settled(): Promise<void> {
  await Promise.all(pending);
}

////////////////////////////////////////////////////////////////////////
//
// Logged requests matching `method` and `path`.  `path` matches the URL
// pathname exactly (query string ignored), e.g.
// `requestsTo("POST", "/api/token/refresh/")`.
//
export async function requestsTo(
  method: string,
  path: string,
): Promise<LoggedRequest[]> {
  await settled();
  return requestLog.filter(
    (r) =>
      r.method === method.toUpperCase() && new URL(r.url).pathname === path,
  );
}

////////////////////////////////////////////////////////////////////////
//
export async function lastRequest(): Promise<LoggedRequest | undefined> {
  await settled();
  return requestLog.at(-1);
}

////////////////////////////////////////////////////////////////////////
//
export function clearRequestLog(): void {
  requestLog.length = 0;
  pending.clear();
}
