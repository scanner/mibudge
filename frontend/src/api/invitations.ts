import { useAuthStore } from "@/stores/auth";
import type { BankAccountInvitation } from "@/types/api";

export function listAccountInvitations(accountId: string): Promise<BankAccountInvitation[]> {
  return useAuthStore().request<BankAccountInvitation[]>(
    `/bank-accounts/${accountId}/invitations/`,
  );
}

export function sendInvitation(accountId: string, inviteeEmail: string): Promise<void> {
  return useAuthStore().request<void>(`/bank-accounts/${accountId}/invite/`, {
    method: "POST",
    body: { invitee_email: inviteeEmail } as unknown as BodyInit,
  });
}

export function cancelInvitation(accountId: string, token: string): Promise<void> {
  return useAuthStore().request<void>(`/bank-accounts/${accountId}/invitations/${token}/cancel/`, {
    method: "POST",
  });
}

export function listMyInvitations(): Promise<BankAccountInvitation[]> {
  return useAuthStore().request<BankAccountInvitation[]>(`/users/me/invitations/`);
}
