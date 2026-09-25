//
// Bank-account co-owner invitations.  Model layer: domain type and DTO
// mapper.
//

// app imports
//
import type { InvitationDto } from "@/api/dto";

////////////////////////////////////////////////////////////////////////
//
export type InvitationStatus = InvitationDto["status"];

export interface Invitation {
  id: string;
  // Identifies the invitation in the accept / decline / cancel URLs.
  token: string;
  bankAccountId: string;
  bankAccountName: string;
  inviteeEmail: string;
  // The inviter's email.
  invitedBy: string | null;
  status: InvitationStatus;
  expiresAt: string;
  createdAt: string;
}

export function invitationFromDto(dto: InvitationDto): Invitation {
  return {
    id: dto.id,
    token: dto.token,
    bankAccountId: dto.bank_account_id,
    bankAccountName: dto.bank_account_name,
    inviteeEmail: dto.invitee_email,
    invitedBy: dto.invited_by ?? null,
    status: dto.status,
    expiresAt: dto.expires_at,
    createdAt: dto.created_at,
  };
}
