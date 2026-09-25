//
// `useAccountHub`: the data behind the Account tab -- the user's
// initials, each bank account's Unallocated balance and next funding
// total, and the default-account setting.  Feature composable
// (settings).
//

// 3rd party imports
//
import { computed, onMounted, ref } from "vue";

// app imports
//
import { api } from "@/api";
import { describeError } from "@/api/errors";
import type { BankAccount, FundingSummary } from "@/models/bankAccount";
import { fundingSummaryFromDto } from "@/models/bankAccount";
import { useAccountContextStore } from "@/stores/accountContext";
import { useBudgetsStore } from "@/stores/budgets";
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

  const initials = computed(() => initialsOf(session.user?.name || session.user?.username || ""));
  const fundingSummaries = ref(new Map<string, FundingSummary>());
  const settingDefault = ref(false);
  const defaultAccountError = ref<string | null>(null);

  ////////////////////////////////////////////////////////////////////
  //
  // Refresh the account list, then load each account's Unallocated
  // budget and funding summary in parallel.  These only decorate the
  // page: a failed refresh leaves the cached account list, and each
  // other failure leaves its value blank.
  //
  onMounted(async () => {
    await ctx.refresh().catch(() => undefined);
    const tasks: Promise<unknown>[] = [];
    for (const account of ctx.accounts) {
      const unallocId = account.unallocatedBudgetId;
      if (unallocId && !budgets.byId(unallocId)) tasks.push(budgets.fetchOne(unallocId));
      tasks.push(
        api.bankAccounts.fundingSummary(account.id).then((dto) => {
          fundingSummaries.value.set(account.id, fundingSummaryFromDto(dto));
        }),
      );
    }
    await Promise.allSettled(tasks);
  });

  function unallocatedFor(account: BankAccount) {
    return budgets.byId(account.unallocatedBudgetId);
  }

  // The next funding total, when there is one to show.
  //
  function nextFundingFor(account: BankAccount) {
    const summary = fundingSummaries.value.get(account.id);
    return summary && !summary.total.isZero() ? summary.total : null;
  }

  // A failure says why; the select shows the saved value again.
  //
  async function setDefaultAccount(accountId: string): Promise<void> {
    settingDefault.value = true;
    defaultAccountError.value = null;
    try {
      await session.updateProfile({ defaultBankAccountId: accountId || null });
    } catch (err) {
      defaultAccountError.value = describeError(err, "Failed to set the default account.");
    } finally {
      settingDefault.value = false;
    }
  }

  return {
    initials,
    unallocatedFor,
    nextFundingFor,
    settingDefault,
    defaultAccountError,
    setDefaultAccount,
  };
}
