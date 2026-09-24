# SPA documentation

The mibudge SPA is a Vue 3 + TypeScript single-page app in `frontend/`,
served by Django at `/app/*` with Vue Router handling every sub-route. It
talks to the backend only through the versioned REST API (`/api/v1/`) and
the JWT endpoints (`/api/token/...`), keeps the access token in memory,
and uses Pinia stores for session, account-context and cached domain
state. `frontend/README.md` covers the stack, source layout, auth flow and
Vite configuration; the documents below go deeper on specific topics.

| Document                   | Purpose                                                                 |
|----------------------------|-------------------------------------------------------------------------|
| [Testing](testing.md)      | Running and writing SPA tests: Vitest, the MSW mock REST API, coverage, CI |

Later SPA documents add their own row to this table.
