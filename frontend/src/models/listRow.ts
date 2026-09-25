//
// Rows of a transaction list that can mix bank transactions and
// budget-to-budget transfers.  Model layer.
//

// app imports
//
import type { InternalTransaction } from "@/models/internalTransaction";
import type { Transaction } from "@/models/transaction";
import { occurredAt } from "@/models/transaction";

////////////////////////////////////////////////////////////////////////
//
export type TransactionListRow =
  | { kind: "tx"; tx: Transaction }
  | { kind: "itx"; itx: InternalTransaction };

////////////////////////////////////////////////////////////////////////
//
// The instant a row sorts and groups by.
//
export function rowInstant(row: TransactionListRow): string {
  return row.kind === "tx" ? occurredAt(row.tx) : row.itx.effectiveDate;
}

// A key unique across both kinds.
//
export function rowKey(row: TransactionListRow): string {
  return row.kind === "tx" ? `tx${row.tx.id}` : `itx${row.itx.id}`;
}

////////////////////////////////////////////////////////////////////////
//
// Transactions, followed by transfers when `transfers` is given.
//
export function listRows(
  transactions: readonly Transaction[],
  transfers: readonly InternalTransaction[] | null,
): TransactionListRow[] {
  const rows: TransactionListRow[] = transactions.map((tx) => ({ kind: "tx", tx }));
  if (transfers) for (const itx of transfers) rows.push({ kind: "itx", itx });
  return rows;
}
