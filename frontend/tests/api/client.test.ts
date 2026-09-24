//
// Transport tests for `src/api/client.ts`: base paths, auth header,
// body encoding, empty responses, and error mapping.
//

// 3rd party imports
//
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

// app imports
//
import { apiFetch, ApiError, authFetch } from "@/api/client";
import { lastRequest, server } from "../mocks/server";

////////////////////////////////////////////////////////////////////////
//
describe("base paths", () => {
  // GIVEN: a resource path such as `/budgets/`
  // WHEN:  it is fetched with `apiFetch`
  // THEN:  the request goes to `/api/v1` + path
  //
  it("apiFetch prefixes /api/v1", async () => {
    await apiFetch("/budgets/", null);
    expect((await lastRequest())?.path).toBe("/api/v1/budgets/");
  });

  // GIVEN: an auth path such as `/token/refresh/`
  // WHEN:  it is fetched with `authFetch`
  // THEN:  the request goes to `/api` + path, outside the versioned tree
  //
  it("authFetch prefixes /api", async () => {
    await authFetch("/token/refresh/", null, { method: "POST" });
    expect((await lastRequest())?.path).toBe("/api/token/refresh/");
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("Authorization header", () => {
  // GIVEN: an access token
  // WHEN:  a request is made with it
  // THEN:  the request carries `Authorization: Bearer <token>`
  //
  it("is sent when there is a token", async () => {
    await apiFetch("/budgets/", "abc123");
    expect((await lastRequest())?.headers.authorization).toBe("Bearer abc123");
  });

  // GIVEN: no access token
  // WHEN:  a request is made
  // THEN:  the request has no `Authorization` header at all
  //
  it("is absent when the token is null", async () => {
    await apiFetch("/budgets/", null);
    expect((await lastRequest())?.headers).not.toHaveProperty("authorization");
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("request bodies", () => {
  // GIVEN: a plain-object body
  // WHEN:  it is sent
  // THEN:  it is JSON-encoded with `Content-Type: application/json`
  //
  it("JSON-encodes a plain object", async () => {
    await apiFetch("/budgets/", "t", {
      method: "POST",
      body: { name: "Rent", paused: false } as unknown as BodyInit,
    });
    const req = await lastRequest();
    expect(req?.headers["content-type"]).toBe("application/json");
    expect(req?.body).toEqual({ name: "Rent", paused: false });
  });

  // GIVEN: a `FormData` body
  // WHEN:  it is sent
  // THEN:  it is passed through untouched and the client sets no
  //        `Content-Type`, leaving the multipart boundary to the browser
  //
  it("passes FormData through without setting Content-Type", async () => {
    const form = new FormData();
    form.append("memo", "lunch");
    await apiFetch("/transactions/x/", "t", { method: "PATCH", body: form });
    const req = await lastRequest();
    expect(req?.headers["content-type"]).toMatch(/^multipart\/form-data; boundary=/);
    expect(req?.body).toEqual({ memo: "lunch" });
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("empty responses", () => {
  // GIVEN: an endpoint that answers with no body
  // WHEN:  the response is 204, or a 2xx that is empty or not JSON
  // THEN:  the call resolves to `null` without a JSON parse error
  //
  it.each([
    ["204 No Content", () => new HttpResponse(null, { status: 204 })],
    [
      "201 with Content-Length 0",
      () => new HttpResponse("", { status: 201, headers: { "Content-Length": "0" } }),
    ],
    ["200 non-JSON", () => new HttpResponse("ok", { status: 200 })],
  ])("resolves to null for %s", async (_label, respond) => {
    server.use(http.post("/api/v1/empty/", respond));
    await expect(apiFetch("/empty/", "t", { method: "POST" })).resolves.toBeNull();
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("error responses", () => {
  // GIVEN: an endpoint that answers with a non-2xx status
  // WHEN:  the request completes
  // THEN:  the call rejects with `ApiError` carrying the status and the
  //        raw response body
  //
  it.each([400, 403, 404, 409, 500])("rejects with ApiError on %i", async (status) => {
    const body = JSON.stringify({ detail: `status ${status}` });
    server.use(http.get("/api/v1/budgets/", () => new HttpResponse(body, { status })));

    const err = await apiFetch("/budgets/", "t").catch((e: unknown) => e);

    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(status);
    expect((err as ApiError).body).toBe(body);
  });
});
