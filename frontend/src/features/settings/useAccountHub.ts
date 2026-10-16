//
// `useAccountHub`: the data behind the Account tab -- the user's
// initials, each bank account's Unallocated balance and next funding
// total, and the default-account setting.  Feature composable
// (settings).
//
// Loads when mounted, and again in the background when any bank
// account or budget may have changed (`stores/invalidation.ts`).
//

// 3rd party imports
//
import { computed, onMounted, ref } from "vue";

// app imports
//
import { api } from "@/api";
import { useOptimistic } from "@/composables/useOptimistic";
import type { BankAccount, FundingSummary } from "@/models/bankAccount";
import { fundingSummaryFromDto } from "@/models/bankAccount";
import { useAccountContextStore } from "@/stores/accountContext";
import { useBudgetsStore } from "@/stores/budgets";
import { useInvalidationStore } from "@/stores/invalidation";
import { useSessionStore } from "@/stores/session";

////////////////////////////////////////////////////////////////////////
//
// Up to two initials from a display name, e.g. "Ada Lovelace" → "AL".
//
export function initialsOf(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0].toUpperCase())
    .join("");
}

////////////////////////////////////////////////////////////////////////
//
export function useAccountHub() {
  const session = useSessionStore();
  const ctx = useAccountContextStore();
  const budgets = useBudgetsStore();

  const initials = computed(() =>
    initialsOf(session.user?.name || session.user?.username || ""),
  );
  const fundingSummaries = ref(new Map<string, FundingSummary>());

  ////////////////////////////////////////////////////////////////////
  //
  // Refresh the account list, then load each account's Unallocated
  // budget (when not cached, or always on a refresh) and funding
  // summary in parallel.  These only decorate the page: a failed
  // refresh leaves the cached account list, and each other failure
  // leaves its value as it was.
  //
  async function load(refresh = false): Promise<void> {
    await ctx.refresh().catch(() => undefined);
    const tasks: Promise<unknown>[] = [];
    for (const account of ctx.accounts) {
      const unallocId = account.unallocatedBudgetId;
      if (unallocId && (refresh || !budgets.byId(unallocId)))
        tasks.push(budgets.fetchOne(unallocId));
      tasks.push(
        api.bankAccounts.fundingSummary(account.id).then((dto) => {
          fundingSummaries.value.set(account.id, fundingSummaryFromDto(dto));
        }),
      );
    }
    await Promise.allSettled(tasks);
  }

  onMounted(() => load());
  useInvalidationStore().onInvalidate(
    () => ({ kinds: ["bankAccounts", "budgets"] }),
    () => load(true),
  );

  function unallocatedFor(account: BankAccount) {
    return budgets.byId(account.unallocatedBudgetId);
  }

  // The next funding total, when there is one to show.
  //
  function nextFundingFor(account: BankAccount) {
    const summary = fundingSummaries.value.get(account.id);
    return summary && !summary.total.isZero() ? summary.total : null;
  }

  // The default account ("" for none), applied optimistically
  // (`useOptimistic`); a refused change shows the saved default again
  // with the server's reason.
  //
  const defaultAccount = useOptimistic(
    (_setting: "default") => session.user?.defaultBankAccountId ?? "",
    async (_setting: "default", accountId: string) => {
      await session.updateProfile({ defaultBankAccountId: accountId || null });
    },
    { errorMessage: "Failed to set the default account." },
  );
  const defaultAccountId = computed(() => defaultAccount.value("default"));
  const defaultAccountError = computed(() => defaultAccount.error("default"));

  function setDefaultAccount(accountId: string): Promise<void> {
    return defaultAccount.set("default", accountId);
  }

  return {
    initials,
    unallocatedFor,
    nextFundingFor,
    defaultAccountId,
    defaultAccountError,
    setDefaultAccount,
  };
}
