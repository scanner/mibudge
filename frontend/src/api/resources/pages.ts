//
// Pagination helpers over DRF's `{count, next, previous, results}`
// envelope.  API layer.
//

// app imports
//
import type { Page } from "@/api/dto";
import type { HttpClient } from "@/api/http";
import { pathOf } from "@/api/http";

////////////////////////////////////////////////////////////////////////
//
export function pagesResource(http: HttpClient) {
  // Fetch the page a `next` / `previous` link points at.
  //
  function fetchPage<T>(url: string): Promise<Page<T>> {
    return http.get<Page<T>>(pathOf(url));
  }

  // Follow `next` links from `first` and return every result, in order.
  //
  async function all<T>(first: Page<T>): Promise<T[]> {
    const out = [...first.results];
    let next = first.next ?? null;
    while (next) {
      const page = await fetchPage<T>(next);
      out.push(...page.results);
      next = page.next ?? null;
    }
    return out;
  }

  return { fetchPage, all };
}
