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
| [Architecture](architecture.md)       | The layers, what each may import, naming, the request lifecycle (401 refresh, `AuthError`), how sections communicate |
| [API and models](api-and-models.md)   | The HTTP transport, `ApiError`, regenerating API types, DTOs vs models, money and date rules, adding a REST resource |
| [State](state.md)                     | Each Pinia store, caching and invalidation, the sign-out reset, store vs composable vs local state |
| [Adding a page](adding-a-page.md)     | Recipe and worked example for a new route; rewriting an existing view incrementally        |
| [Components](components.md)           | Presentational vs feature components, props / emits / `defineModel`, naming                |
| [Testing](testing.md)                 | Running and writing SPA tests: Vitest, the MSW mock REST API, fixtures, coverage, CI       |

Later SPA documents add their own row to this table.
