//
// A page of domain models: DRF's pagination envelope with its results
// mapped.  Model layer.
//

// app imports
//
import type { Page } from "@/api/dto";

////////////////////////////////////////////////////////////////////////
//
export interface ModelPage<T> {
  count: number;
  // Absolute URL of the next page, or `null` on the last page.
  next: string | null;
  results: T[];
}

////////////////////////////////////////////////////////////////////////
//
export function pageFromDto<D, T>(
  page: Page<D>,
  fromDto: (dto: D) => T,
): ModelPage<T> {
  return {
    count: page.count,
    next: page.next ?? null,
    results: page.results.map(fromDto),
  };
}
