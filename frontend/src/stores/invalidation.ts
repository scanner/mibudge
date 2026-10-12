//
// Invalidation signal: what may have changed on the server, and who
// shows it.  Store layer.
//
// Sources say what changed with `invalidate(scope)`: a bank account
// and the kinds of data (`bankAccounts`, `budgets`, `transactions`), or
// everything when the scope is empty.  The sources are the page coming
// back into view after `STALE_AFTER_MS` hidden (`pageShown`), the
// network coming back, and the user asking (pull to refresh, the
// refresh button); a server event stream calls the same entry point
// with narrow scopes.  The signal carries no data: each subscriber
// refetches what it shows through its own store or feature load.
//
// Feature composables subscribe with `onInvalidate(interest, refresh)`,
// where `interest()` names the bank account (omitted: every account)
// and kinds the page shows, or `null` while it shows nothing.  The
// subscription ends with the component that made it.
//
// Signals raised in the same tick are coalesced: each subscriber runs
// at most once per flush.  While the page is hidden, signals are held
// and flushed when it is shown again, so nothing is fetched for a page
// no one is looking at.
//

// 3rd party imports
//
import { defineStore } from "pinia";
import { getCurrentScope, onScopeDispose } from "vue";

////////////////////////////////////////////////////////////////////////
//
// A page hidden for at least this long may have missed a change (a
// bank sync, a funding run, a co-owner's edit), so showing it again
// refreshes everything.
//
export const STALE_AFTER_MS = 60_000;

export type ChangeKind = "bankAccounts" | "budgets" | "transactions";

// What changed.  An omitted field matches every value.
export interface ChangeScope {
  bankAccountId?: string;
  kinds?: readonly ChangeKind[];
}

// What a subscriber shows.  An omitted `bankAccountId` means every
// bank account.
export interface Interest {
  bankAccountId?: string;
  kinds: readonly ChangeKind[];
}

// The interest of a page showing `kinds` for one bank account, or
// `null` while it has none.
export function accountInterest(
  bankAccountId: string | null | undefined,
  kinds: readonly ChangeKind[],
): Interest | null {
  return bankAccountId ? { bankAccountId, kinds } : null;
}

interface Subscriber {
  interest: () => Interest | null;
  refresh: () => unknown;
}

////////////////////////////////////////////////////////////////////////
//
function matches(scope: ChangeScope, interest: Interest): boolean {
  if (
    scope.bankAccountId !== undefined &&
    interest.bankAccountId !== undefined &&
    scope.bankAccountId !== interest.bankAccountId
  )
    return false;
  return !scope.kinds || scope.kinds.some((k) => interest.kinds.includes(k));
}

function pageHidden(): boolean {
  return (
    typeof document !== "undefined" && document.visibilityState === "hidden"
  );
}

////////////////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////
//
export const useInvalidationStore = defineStore("invalidation", () => {
  const subscribers = new Set<Subscriber>();
  let queued: ChangeScope[] = [];
  let flushing: Promise<void> | null = null;
  // Settles the callers waiting on held signals.
  let held: (() => void)[] = [];

  ////////////////////////////////////////////////////////////////////
  //
  function onInvalidate(
    interest: () => Interest | null,
    refresh: () => unknown,
  ): () => void {
    const sub: Subscriber = { interest, refresh };
    subscribers.add(sub);
    const stop = () => void subscribers.delete(sub);
    if (getCurrentScope()) onScopeDispose(stop);
    return stop;
  }

  ////////////////////////////////////////////////////////////////////
  //
  // Run every subscriber that shows something in the queued scopes.
  //
  async function flush(): Promise<void> {
    const scopes = queued;
    queued = [];
    const runs: unknown[] = [];
    for (const sub of subscribers) {
      const interest = sub.interest();
      if (interest && scopes.some((s) => matches(s, interest)))
        runs.push(sub.refresh());
    }
    await Promise.allSettled(runs);
  }

  function scheduleFlush(): Promise<void> {
    flushing ??= Promise.resolve().then(() => {
      flushing = null;
      return flush();
    });
    return flushing;
  }

  ////////////////////////////////////////////////////////////////////
  //
  // Signal a change.  Resolves once the subscribers' refreshes have
  // settled (after the page is shown again, when it is hidden).
  //
  function invalidate(scope: ChangeScope = {}): Promise<void> {
    queued.push(scope);
    if (!pageHidden()) return scheduleFlush();
    return new Promise((resolve) => held.push(resolve));
  }

  // The page is shown again after `hiddenMs` hidden: refresh
  // everything when it may have missed a change, and flush any held
  // signals.
  //
  function pageShown(hiddenMs: number): Promise<void> {
    if (hiddenMs >= STALE_AFTER_MS) queued.push({});
    const waiting = held;
    held = [];
    if (queued.length === 0) return Promise.resolve();
    const done = scheduleFlush();
    void done.then(() => waiting.forEach((resolve) => resolve()));
    return done;
  }

  ////////////////////////////////////////////////////////////////////
  //
  // Held signals belong to the signed-out session.  Subscribers belong
  // to mounted components, which remove them as they unmount.
  //
  function reset(): void {
    queued = [];
    held.forEach((resolve) => resolve());
    held = [];
  }

  return { onInvalidate, invalidate, pageShown, reset };
});
