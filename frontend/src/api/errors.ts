//
// Errors raised by the HTTP transport.  API layer: no Vue, Pinia or
// router imports.
//
// - `ApiError`: the server answered with a non-2xx status.  The body is
//   parsed as a DRF error response into `detail`, `fieldErrors` and
//   `nonFieldErrors`, and `message` is the most specific of those
//   (falling back to `HTTP <status>`).
// - `AuthError`: a request got 401 and the token refresh failed too;
//   the session is over.
//
// `describeError` turns any thrown value into a message for the UI.
//

////////////////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////
//
export class ApiError extends Error {
  readonly status: number;
  // Raw response text, for logging.
  readonly body: string;
  // DRF's `{"detail": "..."}`.
  readonly detail: string | null;
  // DRF's `{"field": ["message", ...]}`, keyed by serializer field.
  readonly fieldErrors: Record<string, string[]>;
  // DRF's `non_field_errors`, or a top-level list of messages.
  readonly nonFieldErrors: string[];

  constructor(status: number, body: string) {
    const parsed = parseDrfError(body);
    super(
      parsed.detail ??
        parsed.nonFieldErrors[0] ??
        firstFieldError(parsed.fieldErrors) ??
        `HTTP ${status}`,
    );
    this.name = "ApiError";
    this.status = status;
    this.body = body;
    this.detail = parsed.detail;
    this.fieldErrors = parsed.fieldErrors;
    this.nonFieldErrors = parsed.nonFieldErrors;
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
//
interface ParsedDrfError {
  detail: string | null;
  fieldErrors: Record<string, string[]>;
  nonFieldErrors: string[];
}

////////////////////////////////////////////////////////////////////////
//
// Parse a DRF error body.  DRF answers validation errors with
// `{"field": ["msg"], "non_field_errors": ["msg"]}`, other errors with
// `{"detail": "msg"}`, and a raised `ValidationError("msg")` with
// `["msg"]`.  Nested serializer errors are flattened to `"a.b"` keys.
// A body that is not JSON yields no messages.
//
export function parseDrfError(body: string): ParsedDrfError {
  const out: ParsedDrfError = { detail: null, fieldErrors: {}, nonFieldErrors: [] };
  let data: unknown;
  try {
    data = body ? JSON.parse(body) : null;
  } catch {
    return out;
  }
  if (Array.isArray(data)) {
    out.nonFieldErrors = data.map(String);
    return out;
  }
  if (!data || typeof data !== "object") return out;

  for (const [key, value] of Object.entries(data as Record<string, unknown>)) {
    if (key === "detail" && typeof value === "string") {
      out.detail = value;
    } else if (key === "non_field_errors") {
      out.nonFieldErrors.push(...messages(value));
    } else if (key !== "code") {
      collectFieldErrors(out.fieldErrors, key, value);
    }
  }
  return out;
}

////////////////////////////////////////////////////////////////////////
//
function messages(value: unknown): string[] {
  if (Array.isArray(value)) return value.filter((v) => typeof v === "string");
  return typeof value === "string" ? [value] : [];
}

function collectFieldErrors(out: Record<string, string[]>, key: string, value: unknown): void {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    for (const [sub, subValue] of Object.entries(value as Record<string, unknown>)) {
      collectFieldErrors(out, `${key}.${sub}`, subValue);
    }
    return;
  }
  const msgs = messages(value);
  if (msgs.length) out[key] = msgs;
}

function firstFieldError(fieldErrors: Record<string, string[]>): string | undefined {
  for (const msgs of Object.values(fieldErrors)) {
    if (msgs[0]) return msgs[0];
  }
  return undefined;
}

////////////////////////////////////////////////////////////////////////
//
// A message for the UI from anything a request can throw: the server's
// DRF message for an `ApiError`, a session notice for `AuthError`, a
// network notice when `fetch` itself failed, otherwise `fallback`.
//
export function describeError(err: unknown, fallback = "Something went wrong."): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof AuthError) return "Your session has expired. Please sign in again.";
  if (err instanceof TypeError) return "Could not reach the server. Check your connection.";
  return fallback;
}

////////////////////////////////////////////////////////////////////////
//
export function isApiError(err: unknown, status?: number): err is ApiError {
  return err instanceof ApiError && (status === undefined || err.status === status);
}
