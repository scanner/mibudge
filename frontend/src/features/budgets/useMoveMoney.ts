//
// `useMoveMoney`: the "Move money" form -- a transfer between this
// budget (or its fill-up goal) and another budget of the account.
// Feature composable (budgets).
//
// `prepare()` loads the account's other budgets and resets the form;
// `submit()` creates the transfer through the budgets store, which
// refetches both budgets so every balance on screen updates.
//

// 3rd party imports
//
import { computed, ref } from "vue";

// app imports
//
import { describeError } from "@/api/errors";
import { Money, toDecimal } from "@/domain/money";
import type { Budget } from "@/models/budget";
import { useAccountContextStore } from "@/stores/accountContext";
import { useBudgetsStore } from "@/stores/budgets";

////////////////////////////////////////////////////////////////////////
//
export type MoveDirection = "into" | "outof";

////////////////////////////////////////////////////////////////////////
//
export function useMoveMoney(budget: () => Budget | null, fillupBudget: () => Budget | null) {
  const ctx = useAccountContextStore();
  const store = useBudgetsStore();

  const otherBudgets = ref<Budget[]>([]);
  const direction = ref<MoveDirection>("outof");
  const targetFillup = ref(false);
  const otherId = ref("");
  // A `type="number"` input's `v-model` yields a number once edited.
  const amount = ref<string | number>("");
  const saving = ref(false);
  const error = ref<string | null>(null);

  ////////////////////////////////////////////////////////////////////
  //
  // Parent budget names keyed by their fill-up goal's id, so a fill-up
  // goal reads "Rent (fill-up)" in the picker.
  //
  const fillupParentNames = computed(() => {
    const map = new Map<string, string>();
    for (const b of otherBudgets.value) {
      if (b.fillupGoalId) map.set(b.fillupGoalId, b.name);
    }
    return map;
  });

  // When moving to / from the fill-up goal, it is not a counterpart.
  //
  const pickerBudgets = computed(() => {
    const fillup = fillupBudget();
    if (targetFillup.value && fillup) return otherBudgets.value.filter((b) => b.id !== fillup.id);
    return otherBudgets.value;
  });

  const parsedAmount = computed(() => toDecimal(amount.value));
  const canSubmit = computed(
    () =>
      !!otherId.value && !!parsedAmount.value && parsedAmount.value.isPositive() && !saving.value,
  );

  function pickerLabel(b: Budget): string {
    if (b.budgetType === "A") {
      const parent = fillupParentNames.value.get(b.id);
      return parent ? `${parent} (fill-up)` : `${b.name} (fill-up)`;
    }
    return b.name;
  }

  // Default counterpart: Unallocated when available, else the first.
  //
  function resetCounterpart(): void {
    const pool = pickerBudgets.value;
    const unalloc = pool.find((b) => b.id === ctx.unallocatedBudgetId);
    otherId.value = unalloc?.id ?? pool[0]?.id ?? "";
  }

  ////////////////////////////////////////////////////////////////////
  //
  async function prepare(): Promise<void> {
    direction.value = "into";
    targetFillup.value = false;
    amount.value = "";
    error.value = null;
    const b = budget();
    const accountId = ctx.activeBankAccountId ?? b?.bankAccountId;
    if (!accountId) return;
    try {
      const list = await store.fetchList({ bank_account: accountId, archived: false });
      otherBudgets.value = list.filter((o) => o.id !== b?.id);
    } catch (err) {
      otherBudgets.value = [];
      error.value = describeError(err, "Failed to load budgets.");
    }
    resetCounterpart();
  }

  function setTarget(toFillup: boolean): void {
    targetFillup.value = toFillup;
    resetCounterpart();
  }

  ////////////////////////////////////////////////////////////////////
  //
  // Resolves `true` once the transfer is made.
  //
  async function submit(): Promise<boolean> {
    const b = budget();
    const value = parsedAmount.value;
    if (!b || !value || !canSubmit.value) return false;
    saving.value = true;
    error.value = null;

    const fillup = fillupBudget();
    const thisId = targetFillup.value && fillup ? fillup.id : b.id;
    const [srcBudgetId, dstBudgetId] =
      direction.value === "outof" ? [thisId, otherId.value] : [otherId.value, thisId];
    try {
      await store.transfer({
        bankAccountId: b.bankAccountId,
        srcBudgetId,
        dstBudgetId,
        amount: Money.of(value, b.balance.currency),
      });
      return true;
    } catch (err) {
      error.value = describeError(err, "Transfer failed. Check the amount and try again.");
      return false;
    } finally {
      saving.value = false;
    }
  }

  return {
    direction,
    targetFillup,
    otherId,
    amount,
    saving,
    error,
    pickerBudgets,
    canSubmit,
    pickerLabel,
    prepare,
    setTarget,
    submit,
  };
}
