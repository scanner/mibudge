//
// Transactions — imported from bank statements; the UI can only update
// `description`, `memo`, `image`, and `document`.  Create and delete
// are not exposed to users (UI_SPEC §4.6).
//

import { useAuthStore } from "@/stores/auth";
import { qs } from "@/api/util";
import type { Paginated, Transaction, TransactionListParams } from "@/types/api";

////////////////////////////////////////////////////////////////////////
//
export function listTransactions(params?: TransactionListParams): Promise<Paginated<Transaction>> {
  return useAuthStore().request<Paginated<Transaction>>(`/transactions/${qs(params)}`);
}

////////////////////////////////////////////////////////////////////////
//
// Fetch the next page from a `next` URL returned by the API.  The URL
// is absolute and already under /api/v1/ — strip that prefix so the
// client's base URL applies cleanly.
//
export function listTransactionsNext(nextUrl: string): Promise<Paginated<Transaction>> {
  const path = nextUrl.replace(/^.*\/api\/v1/, "");
  return useAuthStore().request<Paginated<Transaction>>(path);
}

////////////////////////////////////////////////////////////////////////
//
export function getTransaction(id: string): Promise<Transaction> {
  return useAuthStore().request<Transaction>(`/transactions/${id}/`);
}

////////////////////////////////////////////////////////////////////////
//
// PATCH the mutable subset of a transaction (description, memo).  For
// attachments use `uploadTransactionAttachment`.
//
export function updateTransaction(
  id: string,
  body: Partial<Pick<Transaction, "description" | "memo">>,
): Promise<Transaction> {
  return useAuthStore().request<Transaction>(`/transactions/${id}/`, {
    method: "PATCH",
    body: body as BodyInit,
  });
}

////////////////////////////////////////////////////////////////////////
//
// Multipart upload for photo or document attachments.  `field` must be
// either "image" or "document" — the backend writes the file to the
// matching field on the Transaction model.
//
export function uploadTransactionAttachment(
  id: string,
  field: "image" | "document",
  file: File,
): Promise<Transaction> {
  const form = new FormData();
  form.append(field, file);
  return useAuthStore().request<Transaction>(`/transactions/${id}/`, {
    method: "PATCH",
    body: form,
  });
}
