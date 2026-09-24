//
// Tests for the shared API helpers (`api/util.ts`) and the page-level
// config the Django shell provides (`api/config.ts`).
//

// 3rd party imports
//
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

// app imports
//
import { adminEmail } from "@/api/config";
import { fetchAllPages, qs } from "@/api/util";
import { withAuth } from "../helpers";
import { makePage } from "../mocks/factories";
import { requestsTo, server } from "../mocks/server";

////////////////////////////////////////////////////////////////////////
//
describe("qs", () => {
  // GIVEN: a params object
  // WHEN:  it is turned into a query string
  // THEN:  undefined, null and empty values are dropped, booleans become
  //        "true"/"false", and an empty result yields no "?"
  //
  it.each([
    [undefined, ""],
    [{}, ""],
    [{ a: undefined, b: null, c: "" }, ""],
    [{ archived: false }, "?archived=false"],
    [{ bank_account: "x", page: 2, pending: true }, "?bank_account=x&page=2&pending=true"],
    [{ search: "a&b c" }, "?search=a%26b+c"],
  ])("qs(%j) = %j", (params, expected) => {
    expect(qs(params)).toBe(expected);
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("fetchAllPages", () => {
  // GIVEN: a first page whose `next` links to two further pages
  // WHEN:  all pages are fetched
  // THEN:  each `next` URL is requested under `/api/v1` in order
  //  AND:  the results of every page are returned in order
  //
  it("follows next links and concatenates results", async () => {
    withAuth();
    server.use(
      http.get("/api/v1/budgets/", ({ request }) => {
        const page = new URL(request.url).searchParams.get("page");
        return page === "2"
          ? HttpResponse.json(makePage([2], { next: "http://localhost/api/v1/budgets/?page=3" }))
          : HttpResponse.json(makePage([3]));
      }),
    );
    const first = makePage([1], { next: "https://mibudge.example/api/v1/budgets/?page=2" });

    const all = await fetchAllPages(first);

    expect(all).toEqual([1, 2, 3]);
    const paths = (await requestsTo("GET", "/api/v1/budgets/")).map((r) => r.path);
    expect(paths).toEqual(["/api/v1/budgets/?page=2", "/api/v1/budgets/?page=3"]);
  });

  // GIVEN: a single page with no `next`
  // WHEN:  all pages are fetched
  // THEN:  its results are returned without any request
  //
  it("returns a single page without requesting", async () => {
    expect(await fetchAllPages(makePage(["a"]))).toEqual(["a"]);
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("adminEmail", () => {
  // GIVEN: the Django shell template sets `window.__mibudge.adminEmail`
  // WHEN:  `api/config` is imported
  // THEN:  `adminEmail` holds that address
  //
  it("reads the address from window.__mibudge", () => {
    expect(adminEmail).toBe("admin@example.com");
  });
});
