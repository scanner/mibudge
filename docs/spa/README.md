# SPA documentation

The mibudge SPA is a Vue 3 + TypeScript single-page app in `frontend/`.
Django serves it at `/app/*`, and Vue Router handles every sub-route. It
talks to the backend only through the versioned REST API (`/api/v1/`)
and the JWT endpoints (`/api/token/...`). It keeps the access token in
memory and uses Pinia stores for the session, the active account and
cached domain data.

The source is split into layers (domain → api/models → stores and
composables → features → components and views), each allowed to import
only from the layers below it. Start with [Architecture](architecture.md).
`frontend/README.md` covers the commands and the Vite and Django
integration.

| Document                              | Purpose                                                                                     |
|---------------------------------------|---------------------------------------------------------------------------------------------|
| [Architecture](architecture.md)       | The layers, what each may import, naming, the request lifecycle (401 refresh, `AuthError`), the router (typed names, `meta.access` and the guard, cold boot), how sections communicate |
| [API and models](api-and-models.md)   | The HTTP transport, `ApiError`, regenerating API types, DTOs vs models, money and date rules, adding a REST resource |
| [State](state.md)                     | Each Pinia store, caching and invalidation, settings that save on change (`useOptimistic`), the sign-out reset, store vs composable vs local state |
| [Adding a page](adding-a-page.md)     | Recipe and worked example for a new route; rewriting an existing view incrementally        |
| [Components](components.md)           | Presentational vs feature components, props / emits / `defineModel`, naming                |
| [Styling](styling.md)                 | The design system: tokens, type roles, the `Base*` primitives, the style lint, and how to change a style |
| [Screens](screens.md)                 | What each screen shows and does, the app shell and navigation, and the conventions every screen shares |
| [Testing](testing.md)                 | Running and writing SPA tests: Vitest, the MSW mock REST API, fixtures, coverage, CI       |

Later SPA documents add their own row to this table.

These documents move with `frontend/` if the SPA becomes its own
repository, so they link only to each other, into `frontend/`, and to
the REST API contract (`docs/openapi.yaml` and `docs/api.md`).

## Known gaps

Things the SPA does not do yet, each with the document that covers the
current behaviour:

- **No end-to-end tests.** The suite runs in Vitest against a mock REST
  API. Nothing drives a real browser against a running backend
  ([testing.md](testing.md)).
- **No translation layer.** User-visible text is English, written in
  the templates. Dates, times and amounts already go through
  `DISPLAY_FORMAT` (`domain/displayFormat.ts`), which names the locale
  ([styling.md](styling.md)).
- **Accessibility beyond the floor.** Contrast, focus rings and touch
  targets meet the floor in [styling.md](styling.md), and sheets trap
  focus. A full keyboard and screen-reader pass (landmarks, ARIA
  labelling across screens, reduced motion) comes with the planned
  accessibility work.
- **No live updates.** Another tab, a co-owner or a bank sync changes
  what a page shows only when the page next loads its data. Nothing
  pushes changes to an open page
  ([state.md](state.md#caching-and-invalidation)).
- **Sign-out is client-side.** Signing out clears the tab's state, but
  the refresh cookie stays valid until it expires, because the API has
  no logout endpoint
  ([state.md](state.md#sign-out-resets-every-store)).
- **Hand-written response types.** A few endpoints have no named
  response schema in `docs/openapi.yaml`, so their DTOs are taken from
  inline operation types or written by hand in `api/dto.ts`
  ([api-and-models.md](api-and-models.md#dto-aliases-apidtots)).
