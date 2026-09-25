//
// `useBankAccountCreate`: the new-bank-account form.  Feature
// composable (bankAccounts).
//
// Loads the bank list, validates the required fields, and creates the
// account through the bank-accounts store (so the switcher lists it).
// Opening balances are optional; a blank or unparseable balance is
// left to the server's default of zero.
//

// 3rd party imports
//
import { onMounted, ref } from "vue";

// app imports
//
import { api } from "@/api";
import { describeError } from "@/api/errors";
import { useFormErrors } from "@/composables/useFormErrors";
import type { AccountType } from "@/domain/labels";
import { Money, toDecimal } from "@/domain/money";
import type { Bank } from "@/models/bank";
import { bankFromDto } from "@/models/bank";
import type { BankAccount } from "@/models/bankAccount";
import { useAccountContextStore } from "@/stores/accountContext";
import { useBankAccountsStore } from "@/stores/bankAccounts";

////////////////////////////////////////////////////////////////////////
//
export const ACCOUNT_TYPE_OPTIONS: { value: AccountType; label: string; sub: string }[] = [
  { value: "C", label: "Checking", sub: "Day-to-day spending" },
  { value: "S", label: "Savings", sub: "Set aside funds" },
  { value: "X", label: "Credit card", sub: "Track card charges" },
];

function balance(value: string, currency: string): Money | null {
  const d = toDecimal(value);
  return d ? Money.of(d, currency) : null;
}

////////////////////////////////////////////////////////////////////////
//
export function useBankAccountCreate() {
  const accounts = useBankAccountsStore();
  const ctx = useAccountContextStore();
  const errors = useFormErrors();

  const accountType = ref<AccountType>("C");
  const name = ref("");
  const selectedBankId = ref<string | null>(null);
  const accountNumber = ref("");
  const currency = ref("USD");
  const postedBalance = ref("");
  const availableBalance = ref("");

  const banks = ref<Bank[]>([]);
  const banksLoading = ref(false);
  const saving = ref(false);

  onMounted(async () => {
    banksLoading.value = true;
    try {
      const first = await api.banks.list();
      banks.value = (await api.pages.all(first)).map(bankFromDto);
    } catch (err) {
      banks.value = [];
      errors.setFormError(describeError(err, "Failed to load the list of banks."));
    } finally {
      banksLoading.value = false;
    }
  });

  ////////////////////////////////////////////////////////////////////
  //
  // Create the account; resolves to it, or `null` when validation or
  // the request failed (`error` holds the message).
  //
  async function submit(): Promise<BankAccount | null> {
    if (!name.value.trim()) return fail("Account name is required.");
    if (!selectedBankId.value) return fail("Please select a bank.");
    if (!accountNumber.value.trim()) return fail("Account number is required.");

    saving.value = true;
    errors.clear();
    try {
      const created = await accounts.create({
        accountType: accountType.value,
        name: name.value.trim(),
        bankId: selectedBankId.value,
        currency: currency.value,
        accountNumber: accountNumber.value.trim(),
        postedBalance: balance(postedBalance.value, currency.value),
        availableBalance: balance(availableBalance.value, currency.value),
      });
      await ctx.refresh();
      return created;
    } catch (err) {
      errors.setError(err, { fallback: "Failed to create account.", inlineFields: false });
      return null;
    } finally {
      saving.value = false;
    }
  }

  function fail(message: string): null {
    errors.setFormError(message);
    return null;
  }

  return {
    accountType,
    name,
    selectedBankId,
    accountNumber,
    currency,
    postedBalance,
    availableBalance,
    banks,
    banksLoading,
    saving,
    error: errors.formError,
    submit,
  };
}
