//
// Write order for an entity cache.  Store layer (a helper the caches
// use, not a store).
//
// Each cached record holds the newest answer the SPA has for it.  A
// fetch takes a ticket (`ticket()`) before it sends its request, and
// writes a record only when `accept(id, ticket)` says the ticket is
// newer than the one the record was written with.  A mutation runs
// through `mutating(ids, request)`: while it is in flight its records
// accept no fetch answers, and when it succeeds they take a fresh
// ticket, because its answer is the server's state as of its landing.
//
// So a fetch answered before a mutation landed, or before a later
// fetch was answered, never overwrites the newer answer: a background
// refresh racing a save cannot put the old value back on screen.
//

////////////////////////////////////////////////////////////////////////
//
export interface WriteOrder {
  // A ticket for a fetch about to be sent.
  ticket(): number;
  // Whether a fetch answer with `ticket` may write record `id`; when it
  // may, the record is marked as written with that ticket.
  accept(id: string, ticket: number): boolean;
  // Run a mutation of the records `ids`; on success they are marked
  // as written now.  The caller writes the mutation's answer itself.
  mutating<R>(ids: string[], request: () => Promise<R>): Promise<R>;
  // Mark record `id` as written now (a record a mutation created).
  written(id: string): void;
  clear(): void;
}

export function createWriteOrder(): WriteOrder {
  let seq = 0;
  const writtenAt = new Map<string, number>();
  const inFlight = new Map<string, number>();

  function written(id: string): void {
    writtenAt.set(id, ++seq);
  }

  return {
    ticket: () => ++seq,

    accept(id, ticket) {
      if ((inFlight.get(id) ?? 0) > 0) return false;
      if (ticket <= (writtenAt.get(id) ?? 0)) return false;
      writtenAt.set(id, ticket);
      return true;
    },

    async mutating(ids, request) {
      for (const id of ids) inFlight.set(id, (inFlight.get(id) ?? 0) + 1);
      let ok = false;
      try {
        const result = await request();
        ok = true;
        return result;
      } finally {
        for (const id of ids) {
          const n = (inFlight.get(id) ?? 1) - 1;
          if (n > 0) inFlight.set(id, n);
          else inFlight.delete(id);
          if (ok) written(id);
        }
      }
    },

    written,

    clear() {
      writtenAt.clear();
      inFlight.clear();
    },
  };
}
