# API and models

How the SPA talks to the REST API (`src/api/`) and how server data
becomes the objects the UI works with (`src/models/`). See
[architecture.md](architecture.md) for where these layers sit.

---

## The transport: `api/http.ts`

`createHttpClient(config)` returns an `HttpClient`. It is the only place
the SPA calls `fetch`; the architecture test enforces that.

```ts
interface HttpClient {
  request<T>(path: string, options?: RequestOptions): Promise<T>;
  get<T>(path: string, query?: object): Promise<T>;
  post<T>(path: string, json?: unknown): Promise<T>;
  patch<T>(path: string, json: unknown): Promise<T>;
  delete<T = null>(path: string): Promise<T>;
  refresh(): Promise<boolean>; // single-flight token refresh
}

interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  json?: unknown;     // JSON body, sets Content-Type
  form?: FormData;    // multipart body; the browser sets the boundary
  query?: object;     // ?a=1&b=true; undefined / null / "" are dropped
  auth?: boolean;     // false: no Authorization header, no 401 refresh
  signal?: AbortSignal;
}
```

What the client does on every request:

- Resolves `path` against `baseUrl` (default: the page origin).
- Sends `Authorization: Bearer <getToken()>` unless `auth: false`.
- On 401, runs the single-flight `refresh()` and retries once. When the
  refresh fails it calls `onAuthFailure` and throws `AuthError`.
- Throws `ApiError` for any other non-2xx.
- Resolves to `null` for a 204, an empty body or a non-JSON body.

The config callbacks (`getToken`, `refresh`, `onAuthFailure`) come from
the session store through `createSessionHttpClient()` in
`stores/session.ts`, so `api/` imports nothing from Vue or Pinia.

`toQueryString(params)` and `pathOf(url)` are exported helpers.
`pathOf` turns DRF's absolute `next` links into a path, so paging stays
on `baseUrl`.

### The `api` registry

`api/index.ts` exports one object with a namespace per resource:

```ts
import { api } from "@/api";

const page = await api.budgets.list({ bank_account: accountId, archived: false });
const all = await api.pages.all(page);        // follow every `next` link
await api.transactions.update(id, { memo: null });
```

`initApi(http)` binds the resource modules to a client. `main.ts` calls
it once and `tests/setup.ts` calls it before each test. Only stores and
feature composables import `api`.

---

## Errors: `api/errors.ts`

```ts
class ApiError extends Error {
  status: number;
  body: string;                             // raw response text
  detail: string | null;                    // DRF {"detail": "..."}
  fieldErrors: Record<string, string[]>;    // DRF {"field": ["..."]}, nested keys as "a.b"
  nonFieldErrors: string[];                 // non_field_errors, or a top-level list
  // message: detail ?? nonFieldErrors[0] ?? first field error ?? `HTTP <status>`
}

class AuthError extends Error {}            // refresh failed; the session is over
```

Helpers:

- `describeError(err, fallback?)` returns one line for the UI. For an
  `ApiError` that is the server's message. For an `AuthError` it is a
  session-expired notice, and for a `TypeError` (the network failed) a
  connection notice. Anything else gets `fallback`.
- `isApiError(err, status?)` narrows the type, optionally to one status:
  `if (isApiError(err, 409)) ...`.
- `parseDrfError(body)` is what `ApiError` uses internally.

In a form, `useFormErrors().setError(err, { fallback, statusMessages })`
puts each field's message next to its input, and the rest into a
form-level message.

---

## Generated types: `api/schema.d.ts`

`api/schema.d.ts` is generated from `docs/openapi.yaml` by
[openapi-typescript](https://openapi-ts.dev/). Never edit it by hand.
It is excluded from formatting (`frontend/.prettierignore`).

Regenerate it whenever the REST API changes:

```sh
make api-schema                       # repo root: refresh docs/openapi.yaml
cd frontend && pnpm gen:api-types     # regenerate src/api/schema.d.ts
pnpm type-check                       # see what the change broke
```

`pnpm gen:api-types` runs openapi-typescript. It then runs
`scripts/stamp-api-types-header.mjs`, which prepends the "generated
file" header.

The Drone `frontend lint` step runs
`pnpm gen:api-types && git diff --exit-code src/api/schema.d.ts`.
Committing an API change without regenerating the types fails CI.

### DTO aliases: `api/dto.ts`

Code never indexes `components["schemas"]` directly. `api/dto.ts` names
each schema type:

| Kind                     | Name                     | Example                                            |
|--------------------------|--------------------------|----------------------------------------------------|
| Response body            | `<Thing>Dto`             | `BudgetDto = Schemas["Budget"]`                    |
| Create body              | `<Thing>CreateDto`       | `BudgetCreateDto = Schemas["BudgetRequest"]`       |
| Partial update body      | `<Thing>UpdateDto`       | `BudgetUpdateDto = Schemas["PatchedBudgetRequest"]` |
| List query parameters    | `<Thing>ListQuery`       | `operations["budgets_list"]["parameters"]["query"]` |
| Enum                     | `<Enum>Dto`              | `BudgetTypeDto = Schemas["BudgetTypeEnum"]`        |
| Inline response          | from `operations[...]`   | `FundingSummaryDto`                                |

`api/dto.ts` hand-writes a type only where the schema cannot express the
response, and says why next to it. For example, `AccessTokenDto` exists
because the token endpoints document no response body.

---

## DTO vs model

A **DTO** is exactly what goes over the wire. It has snake_case keys,
money as a decimal string plus a sibling `*_currency`, dates as strings,
and foreign keys as bare ids. Only `api/resources/` and `models/` use
DTOs.

A **model** is what the rest of the SPA uses. It has camelCase keys,
`Money` for amounts, `LocalDate` for calendar dates, `...Id` suffixes on
foreign keys, and `null` rather than `""` or a missing key.

Each file in `models/` has:

- the model interface (`Budget`);
- `<thing>FromDto(dto)`, which maps a response to the model;
- `<thing>ToCreateDto(input)` / `<thing>ToUpdateDto(input)` where the UI
  writes, mapping an input shape to a request body;
- pure helpers over lists of the model (`fillupIndex`,
  `budgetNameIndex`, `indexByTransaction`, ...);
- compile-time checks that the domain enum unions still match the
  schema:

  ```ts
  export type BudgetTypeMatchesSchema = Expect<Equal<BudgetType, BudgetTypeDto>>;
  ```

  When the server adds an enum value and the types are regenerated,
  `vue-tsc` fails until `domain/labels.ts` is updated.

`models/page.ts` has `ModelPage<T>` and `pageFromDto(page, fromDto)` for
lists the UI pages through (`useInfiniteList`).

Mappers never throw on odd server data. They fall back to a safe value
(`budgetType ?? "G"`, `toLocalDate("")` → `null`) and say so in a
comment.

---

## Money rules

- Amounts are `Money` (`domain/money.ts`), which wraps a `decimal.js`
  `Decimal` plus a currency. Arithmetic is exact: `plus`, `minus`,
  `abs`, `negated`, `cmp`, `equals`, `isZero`, `isNegative`,
  `isPositive`, and `sumMoney(values)`.
- Build one from the API with `Money.of(dto.amount, dto.amount_currency)`,
  or `Money.ofNullable(...)` for a nullable field. Send it back with
  `money.toDecimalString()`.
- Never use `parseFloat` / `Number` on an amount. The only conversion to
  a number is inside `formatMoney`, for `Intl.NumberFormat`.
- Display every amount through `formatMoney(money, { signDisplay })`, or
  the `MoneyAmount` component that wraps it. There is no other currency
  formatter.

## Date rules

The API sends two kinds of date, and `domain/dates.ts` treats them
differently:

- **Calendar dates** (`target_date`, `next_recurrence`,
  `next_funding.date`) are `"YYYY-MM-DD"` strings. The model carries
  them as `LocalDate`, a branded string built with `toLocalDate()`, so
  an arbitrary string or a datetime cannot be passed where a date is
  expected. Format them with `formatLocalDate(date, opts)`. They render
  the same day in every browser zone and profile zone, because the
  formatter anchors them at UTC midnight and formats with
  `timeZone: "UTC"`. Do arithmetic with `addDays` and `daysBetween`.
- **Instants** (`transaction_date`, `created_at`) are ISO datetimes.
  Their calendar day depends on a zone, and the SPA always uses the
  profile zone (`useSessionStore().timezone`), passed explicitly. Use
  `txDateStr(iso, tz)`, `formatInstantDate(iso, opts, tz)` and
  `formatTxDateLong(iso, tz)`.
- "Today" is `todayDateStr(tz, now?)`. The clock and zone are
  parameters, so tests pass them in.
- Never call `new Date("YYYY-MM-DD")` or `toLocaleDateString` on a
  calendar date. It parses as UTC and formats in the browser zone,
  which shows the previous day west of UTC.

---

## Adding a REST resource, end to end

This walks through a worked example: letting the SPA create transaction
categories (`POST /api/v1/transaction-categories/`). The server already
supports it; the SPA only lists and reads them today.

1. **Server and schema.** Make the backend change, then run
   `make api-schema` at the repo root so `docs/openapi.yaml` is current.
2. **Types.** Run `cd frontend && pnpm gen:api-types`, then name the new
   schema types in `src/api/dto.ts`:

   ```ts
   export type TransactionCategoryCreateDto = Schemas["TransactionCategoryRequest"];
   ```

3. **Resource function.** Add the call to its module in
   `src/api/resources/`, or create a module for a new resource:

   ```ts
   // src/api/resources/transactionCategories.ts
   create(body: TransactionCategoryCreateDto): Promise<TransactionCategoryDto> {
     return http.post(`${V1}/transaction-categories/`, body);
   },
   ```

   A new module exports `<resource>Resource(http)` and is added to
   `createApi` in `src/api/index.ts`.
4. **Model.** In `src/models/transactionCategory.ts`, add an input type
   and a mapper for the request body. Response mapping reuses
   `transactionCategoryFromDto`:

   ```ts
   export interface TransactionCategoryInput { group: string; name: string }

   export function transactionCategoryToCreateDto(
     input: TransactionCategoryInput,
   ): TransactionCategoryCreateDto {
     return { group: input.group, name: input.name };
   }
   ```

5. **Caller.** Decide who calls the endpoint (see [state.md](state.md)).
   Data shared across pages goes in a store action that updates the
   cache. Data for one section goes in a feature composable. Either way,
   the caller maps the result with `*FromDto` before storing or
   returning it.
6. **Tests:**
   - `tests/mocks/handlers.ts`: a default handler for the endpoint,
     shaped per `docs/openapi.yaml`.
   - `tests/mocks/factories.ts`: a `make*` factory if the resource is new.
   - `tests/api/resources.test.ts`: one row with the call, method, path
     and body.
   - `tests/models/`: a table for the mapper, covering nulls and
     defaults.
   - A test for the store action or feature composable that calls it.
7. **Checks.** Run `pnpm type-check && pnpm test:coverage`. The `api/`
   and `models/` coverage thresholds are 80% lines.
