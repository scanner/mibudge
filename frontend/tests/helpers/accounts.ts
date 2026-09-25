//
// Account fixtures: seed the bank-accounts cache and the account
// context without going through the API.
//

// app imports
//
import type { BankAccountDto } from "@/api/dto";
import { bankAccountFromDto } from "@/models/bankAccount";
import { useAccountContextStore } from "@/stores/accountContext";
import { useBankAccountsStore } from "@/stores/bankAccounts";

////////////////////////////////////////////////////////////////////////
//
// Make `accounts` the user's bank accounts and the first one (or
// `activeId`) the active account.  Returns the account-context store.
//
export function withAccounts(accounts: BankAccountDto[], activeId?: string) {
  useBankAccountsStore().setAll(accounts.map(bankAccountFromDto));
  const ctx = useAccountContextStore();
  ctx.setActive(activeId ?? accounts[0]?.id ?? null);
  return ctx;
}
