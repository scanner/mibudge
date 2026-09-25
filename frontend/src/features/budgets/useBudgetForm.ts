//
// `useBudgetForm`: state and submit for the budget create / edit form.
// Feature composable (budgets).
//
// Field refs hold what the inputs show; `submit()` turns them into a
// `BudgetInput` and saves through the budgets store, which caches the
// result for every other reader.  A `type="number"` input's `v-model`
// yields a JS number once edited, so amounts are parsed with
// `toDecimal` whatever their type.
//

// 3rd party imports
//
import { computed, ref } from "vue";

// app imports
//
import { useFormErrors } from "@/composables/useFormErrors";
import { toLocalDate } from "@/domain/dates";
import type { BudgetType, FundingType } from "@/domain/labels";
import { Money, toDecimal } from "@/domain/money";
import { combineDtstart, DEFAULT_RRULE, extractDtstart, stripToIntervalOnly } from "@/domain/rrule";
import type { Budget, BudgetInput } from "@/models/budget";
import { useAccountContextStore } from "@/stores/accountContext";
import { useBudgetsStore } from "@/stores/budgets";

////////////////////////////////////////////////////////////////////////
//
function moneyField(value: string | number): Money | null {
  const d = toDecimal(value);
  return d ? Money.of(d) : null;
}

////////////////////////////////////////////////////////////////////////
//
export function useBudgetForm(mode: "create" | "edit", budget?: Budget) {
  const ctx = useAccountContextStore();
  const store = useBudgetsStore();
  const errors = useFormErrors();

  ////////////////////////////////////////////////////////////////////
  //
  // Field state, initialised from `budget` when editing.
  //
  const budgetType = ref<BudgetType>(budget?.budgetType ?? "R");
  const name = ref(budget?.name ?? "");
  const targetBalance = ref<string | number>(budget?.targetBalance?.toDecimalString() ?? "");
  const targetDate = ref<string>(budget?.targetDate ?? "");
  const fundingType = ref<FundingType>(budget?.fundingType ?? "D");
  const fundingAmount = ref<string | number>(budget?.fundingAmount?.toDecimalString() ?? "");
  const fundingSchedule = ref(budget?.fundingSchedule ?? DEFAULT_RRULE);

  const existingRecurrence = extractDtstart(budget?.recurrenceSchedule ?? DEFAULT_RRULE);
  const recurrenceSchedule = ref(existingRecurrence.rrule);
  // Prefer the server-computed next refresh date; the schedule's
  // DTSTART is only the rule anchor and goes stale once a cycle has
  // elapsed.  Saving the next occurrence back as DTSTART is safe: it is
  // on-phase with the rule, so the schedule itself is unchanged.
  //
  const nextRefreshDate = ref<string>(budget?.nextRecurrence ?? existingRecurrence.dtstart ?? "");

  const paused = ref(budget?.paused ?? false);
  const saving = ref(false);

  ////////////////////////////////////////////////////////////////////
  //
  const isGoal = computed(() => budgetType.value === "G");
  const isRecurring = computed(() => budgetType.value === "R");
  const isCapped = computed(() => budgetType.value === "C");
  const canSubmit = computed(() => name.value.trim().length > 0 && !saving.value);
  const accountName = computed(() => ctx.activeBankAccount?.name ?? "—");

  ////////////////////////////////////////////////////////////////////
  //
  function toInput(): BudgetInput {
    const input: BudgetInput = {
      name: name.value.trim(),
      fundingType: fundingType.value,
      fundingSchedule: fundingSchedule.value,
      paused: paused.value,
    };
    const target = moneyField(targetBalance.value);
    if (target) input.targetBalance = target;

    if (isGoal.value) {
      if (fundingType.value === "D") {
        const date = toLocalDate(targetDate.value);
        if (date) input.targetDate = date;
      } else {
        input.targetDate = null;
        input.fundingAmount = moneyField(fundingAmount.value);
      }
    } else if (isRecurring.value) {
      // The refresh-cycle picker is interval-only; the chosen date is
      // the DTSTART anchor that supplies the day-of-month/-year.  Strip
      // any BY* parts carried over from an older rule (e.g.
      // BYMONTHDAY=1 from the create default) -- the API rejects them,
      // and they would override DTSTART and refresh the budget on the
      // wrong day.
      //
      const cycle = stripToIntervalOnly(recurrenceSchedule.value);
      input.recurrenceSchedule = nextRefreshDate.value
        ? combineDtstart(cycle, nextRefreshDate.value)
        : cycle;
    } else if (isCapped.value) {
      // Capped always uses Fixed Amount funding.
      input.fundingType = "F";
      input.fundingAmount = moneyField(fundingAmount.value);
    }
    return input;
  }

  ////////////////////////////////////////////////////////////////////
  //
  // Save and resolve to the saved budget, or `null` when saving failed
  // (`errors.formError` then holds the message).
  //
  async function submit(): Promise<Budget | null> {
    if (!canSubmit.value) return null;
    saving.value = true;
    errors.clear();
    try {
      const input = toInput();
      if (mode === "edit" && budget) return await store.update(budget.id, input);
      const accountId = ctx.activeBankAccountId;
      if (!accountId) {
        errors.setFormError("Select a bank account first.");
        return null;
      }
      return await store.create({
        ...input,
        name: input.name ?? "",
        budgetType: budgetType.value,
        bankAccountId: accountId,
      });
    } catch (err) {
      errors.setError(err, { fallback: "Failed to save budget.", inlineFields: false });
      return null;
    } finally {
      saving.value = false;
    }
  }

  return {
    budgetType,
    name,
    targetBalance,
    targetDate,
    fundingType,
    fundingAmount,
    fundingSchedule,
    recurrenceSchedule,
    nextRefreshDate,
    paused,
    saving,
    isGoal,
    isRecurring,
    isCapped,
    canSubmit,
    accountName,
    error: errors.formError,
    submit,
  };
}
