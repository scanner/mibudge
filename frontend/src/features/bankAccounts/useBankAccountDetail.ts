//
// `useBankAccountDetail`: one bank account with its bank name, budget
// count and Unallocated balance, plus the inline edit, the automatic
// funding toggle and delete.  Feature composable (bankAccounts).
//
// The account is read from the bank-accounts store, so a rename shows
// in the account switcher and the top bar at once.  Loads follow the
// `id` getter; a response for a previous id is ignored.
//
// A failed toggle or delete sets `autoFundingError` / `deleteError`
// with the server's message when it sent one.  The bank's name is
// cosmetic: when it cannot be loaded the page shows none.
//

// 3rd party imports
//
import { computed, ref } from "vue";

// app imports
//
import { api } from "@/api";
import { describeError } from "@/api/errors";
import { useFormErrors } from "@/composables/useFormErrors";
import { useOptimistic } from "@/composables/useOptimistic";
import { useResource } from "@/composables/useResource";
import { formatInstantDate } from "@/domain/dates";
import { bankFromDto } from "@/models/bank";
import { budgetFromDto } from "@/models/budget";
import { useAccountContextStore } from "@/stores/accountContext";
import { useBankAccountsStore } from "@/stores/bankAccounts";
import { useBudgetsStore } from "@/stores/budgets";

////////////////////////////////////////////////////////////////////////
//
interface Loaded {
  id: string;
  bankName: string | null;
  budgetCount: number;
}

////////////////////////////////////////////////////////////////////////
//
export function useBankAccountDetail(id: () => string) {
  const accounts = useBankAccountsStore();
  const budgets = useBudgetsStore();
  const ctx = useAccountContextStore();

  ////////////////////////////////////////////////////////////////////
  //
  const resource = useResource(
    id,
    async (accountId: string): Promise<Loaded> => {
      const [account, budgetPage] = await Promise.all([
        accounts.fetchOne(accountId),
        api.budgets.list({ bank_account: accountId }),
      ]);
      const list = budgetPage.results.map(budgetFromDto);
      for (const b of list) budgets.upsert(b);
      const bankName = await api.banks
        .get(account.bankId)
        .then((dto) => bankFromDto(dto).name)
        .catch(() => null);
      return {
        id: accountId,
        bankName,
        // User-facing budgets: not Unallocated, not fill-up goals.
        budgetCount: list.filter(
          (b) => b.id !== account.unallocatedBudgetId && b.budgetType !== "A",
        ).length,
      };
    },
    { errorMessage: "Failed to load account." },
  );

  const account = computed(() => accounts.byId(resource.data.value?.id));
  const unallocated = computed(() =>
    budgets.byId(account.value?.unallocatedBudgetId),
  );
  const createdDate = computed(() =>
    account.value
      ? formatInstantDate(account.value.createdAt, {
          year: "numeric",
          month: "long",
          day: "numeric",
        })
      : "",
  );

  ////////////////////////////////////////////////////////////////////
  //
  // Inline edit of name and account number.
  //
  const editing = ref(false);
  const editName = ref("");
  const editAccountNumber = ref("");
  const saving = ref(false);
  const editErrors = useFormErrors();

  function startEdit(): void {
    if (!account.value) return;
    editName.value = account.value.name;
    editAccountNumber.value = account.value.accountNumber ?? "";
    editErrors.clear();
    editing.value = true;
  }

  function cancelEdit(): void {
    editing.value = false;
    editErrors.clear();
  }

  async function saveEdit(): Promise<void> {
    const current = account.value;
    if (!current || !editName.value.trim()) {
      editErrors.setFormError("Name is required.");
      return;
    }
    saving.value = true;
    editErrors.clear();
    try {
      const number = editAccountNumber.value.trim();
      await accounts.update(current.id, {
        name: editName.value.trim(),
        ...(number !== (current.accountNumber ?? "")
          ? { accountNumber: number || null }
          : {}),
      });
      editing.value = false;
    } catch (err) {
      editErrors.setError(err, { fallback: "Failed to save." });
    } finally {
      saving.value = false;
    }
  }

  ////////////////////////////////////////////////////////////////////
  //
  // Automatic funding toggle, applied optimistically per account
  // (`useOptimistic`); a refused change shows the store's value again.
  //
  const autoFunding = useOptimistic(
    (accountId: string) =>
      accounts.byId(accountId)?.autoFundingEnabled ?? false,
    async (accountId: string, enabled: boolean) => {
      await accounts.update(accountId, { autoFundingEnabled: enabled });
    },
    { errorMessage: "Failed to change automatic funding." },
  );
  const autoFundingEnabled = computed(() =>
    account.value ? autoFunding.value(account.value.id) : false,
  );
  const autoFundingError = autoFunding.error;

  function toggleAutoFunding(): Promise<void> {
    const current = account.value;
    if (!current) return Promise.resolve();
    return autoFunding.set(current.id, !autoFundingEnabled.value);
  }

  ////////////////////////////////////////////////////////////////////
  //
  // Delete the account; when it was the active one, the account
  // context moves to the first remaining account.  Resolves `true`
  // once deleted.
  //
  const deleting = ref(false);
  const deleteError = ref<string | null>(null);

  async function deleteAccount(): Promise<boolean> {
    const current = account.value;
    if (!current) return false;
    deleting.value = true;
    deleteError.value = null;
    try {
      await accounts.remove(current.id);
    } catch (err) {
      deleteError.value = describeError(err, "Failed to delete the account.");
      return false;
    } finally {
      deleting.value = false;
    }
    // The account is gone; a failed refresh leaves the cached list.
    await ctx.refresh().catch(() => undefined);
    return true;
  }

  return {
    account,
    bankName: computed(() => resource.data.value?.bankName ?? null),
    budgetCount: computed(() => resource.data.value?.budgetCount ?? null),
    unallocated,
    createdDate,
    loading: resource.loading,
    error: resource.error,
    editing,
    editName,
    editAccountNumber,
    saving,
    nameError: editErrors.formError,
    startEdit,
    cancelEdit,
    saveEdit,
    autoFundingEnabled,
    toggleAutoFunding,
    autoFundingError,
    deleting,
    deleteError,
    deleteAccount,
  };
}
