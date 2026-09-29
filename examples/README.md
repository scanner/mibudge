# API examples

Worked examples for the API reference, `docs/api.md`. `make api-docs`
renders each one under its endpoint.

Each file is one endpoint's example, named after the endpoint's
`operationId` in `docs/openapi.yaml` (for example
`transactions_splits_create.json`):

```json
{
  "summary": "Put $60.00 of an $82.47 purchase in Groceries",
  "description": "Optional: what the example shows.",
  "request": {"splits": {"c1d2e3f4-...": "60.00"}},
  "response": {
    "status": "200",
    "summary": "Optional: what the response shows",
    "body": [{"id": "...", "amount": "-60.00"}]
  }
}
```

`request` and `response` are each optional; `response.status` names the
documented status the body belongs to.

The data is fake but shared: one checking account, its budgets and a
grocery purchase, so an id in one example is the same object in another.
Reuse those ids when adding an example, and check a new example against
the running API: the schema test catches a wrong shape, not a request the
server would refuse.

`app/tests/test_api_examples.py` checks every file against the schema: the
operation exists, the request is a valid body naming only fields the
endpoint accepts, and the response is a valid body for its status. The doc
generator refuses a file whose name matches no operation.
