//
// Bank transactions.  Model layer: domain type and DTO mappers for
// `/api/v1/transactions/`.
//

// app imports
//
import type {
  TransactionDto,
  TransactionTypeDto,
  TransactionUpdateDto,
} from "@/api/dto";
import type { TransactionType } from "@/domain/labels";
import { DEFAULT_CURRENCY, Money } from "@/domain/money";
import type { Equal, Expect } from "@/models/schemaCheck";

export type TransactionTypeMatchesSchema = Expect<
  Equal<TransactionType, TransactionTypeDto>
>;

////////////////////////////////////////////////////////////////////////
//
// Merchant enrichment from the importer.  `name`, `category`,
// `categoryCode` and `intermediary` are importer-owned; the location
// fields are user-editable and filled by enrichment only when empty.
//
export interface Merchant {
  name: string | null;
  intermediary: string | null;
  category: string | null;
  categoryCode: string | null;
  address: string | null;
  city: string | null;
  region: string | null;
  country: string | null;
  latitude: string | null;
  longitude: string | null;
}

////////////////////////////////////////////////////////////////////////
//
export interface Transaction {
  id: string;
  bankAccountId: string;
  // Negative for money leaving the account.
  amount: Money;
  party: string | null;
  // Instants (ISO datetimes).  `transactionDate` is absent for some
  // imports; `occurredAt` picks the right one for display.
  postedDate: string;
  transactionDate: string | null;
  // `""` when the bank gave no type.
  transactionType: TransactionType | "";
  pending: boolean;
  memo: string | null;
  rawDescription: string;
  description: string;
  descriptionUserEdited: boolean;
  categoryId: string | null;
  categoryFullName: string | null;
  merchant: Merchant;
  virtualCardNumber: string | null;
  hasDetails: boolean;
  bankTransactionId: string | null;
  // The counterpart transaction on another account (e.g. a card
  // payment's credit on the card), when the importer linked one.
  linkedTransactionId: string | null;
  // Account balances right after this transaction.
  accountPostedBalance: Money;
  accountAvailableBalance: Money;
  image: string | null;
  document: string | null;
  createdAt: string;
}

////////////////////////////////////////////////////////////////////////
//
export function transactionFromDto(dto: TransactionDto): Transaction {
  const currency = dto.amount_currency || DEFAULT_CURRENCY;
  return {
    id: dto.id,
    bankAccountId: dto.bank_account,
    amount: Money.of(dto.amount, currency),
    party: dto.party ?? null,
    postedDate: dto.posted_date,
    transactionDate: dto.transaction_date ?? null,
    transactionType: dto.transaction_type ?? "",
    pending: dto.pending,
    memo: dto.memo ?? null,
    rawDescription: dto.raw_description,
    description: dto.description ?? "",
    descriptionUserEdited: dto.description_user_edited ?? false,
    categoryId: dto.category ?? null,
    categoryFullName: dto.category_full_name ?? null,
    merchant: {
      name: dto.merchant_name ?? null,
      intermediary: dto.merchant_intermediary ?? null,
      category: dto.merchant_category ?? null,
      categoryCode: dto.merchant_category_code ?? null,
      address: dto.merchant_address ?? null,
      city: dto.merchant_city ?? null,
      region: dto.merchant_region ?? null,
      country: dto.merchant_country ?? null,
      latitude: dto.merchant_latitude ?? null,
      longitude: dto.merchant_longitude ?? null,
    },
    virtualCardNumber: dto.virtual_card_number ?? null,
    hasDetails: dto.has_details ?? false,
    bankTransactionId: dto.bank_transaction_id ?? null,
    // The schema marks this non-null; the server sends `null` for an
    // unlinked transaction.
    linkedTransactionId: dto.linked_transaction ?? null,
    accountPostedBalance: Money.of(
      dto.bank_account_posted_balance,
      dto.bank_account_posted_balance_currency || currency,
    ),
    accountAvailableBalance: Money.of(
      dto.bank_account_available_balance,
      dto.bank_account_available_balance_currency || currency,
    ),
    image: dto.image ?? null,
    document: dto.document ?? null,
    createdAt: dto.created_at,
  };
}

////////////////////////////////////////////////////////////////////////
//
// The instant a transaction happened: its transaction date, or its
// posted date when the bank gave none.
//
export function occurredAt(
  tx: Pick<Transaction, "transactionDate" | "postedDate">,
): string {
  return tx.transactionDate ?? tx.postedDate;
}

////////////////////////////////////////////////////////////////////////
//
// The name a row shows: the party, else the description, else the raw
// bank text.
//
export function displayName(
  tx: Pick<Transaction, "party" | "description" | "rawDescription">,
): string {
  return tx.party || tx.description || tx.rawDescription;
}

////////////////////////////////////////////////////////////////////////
//
// Newest first by occurrence, then by creation.
//
export function compareNewestFirst(a: Transaction, b: Transaction): number {
  const [da, db] = [occurredAt(a), occurredAt(b)];
  if (da !== db) return da > db ? -1 : 1;
  return a.createdAt > b.createdAt ? -1 : a.createdAt < b.createdAt ? 1 : 0;
}

////////////////////////////////////////////////////////////////////////
//
// The user-editable text fields.  An empty memo is sent as `null`, which
// clears it on the server.
//
export interface TransactionTextUpdate {
  description?: string;
  memo?: string | null;
}

export function transactionToUpdateDto(
  update: TransactionTextUpdate,
): Pick<TransactionUpdateDto, "description" | "memo"> {
  const dto: Pick<TransactionUpdateDto, "description" | "memo"> = {};
  if (update.description !== undefined) dto.description = update.description;
  if (update.memo !== undefined) dto.memo = update.memo || null;
  return dto;
}
