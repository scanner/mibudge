//
// Bank-account co-owner invitations.  API layer.
//
// The two list endpoints answer a plain JSON array; the schema
// describes them as paginated (a drf-spectacular annotation gap), so
// the element type comes from the schema and the array is declared
// here.
//

// app imports
//
import type { InvitationDto } from "@/api/dto";
import type { HttpClient } from "@/api/http";
import { V1 } from "./paths";

////////////////////////////////////////////////////////////////////////
//
export function invitationsResource(http: HttpClient) {
  return {
    // Pending invitations for one account.
    //
    listForAccount(accountId: string): Promise<InvitationDto[]> {
      return http.get(`${V1}/bank-accounts/${accountId}/invitations/`);
    },

    // Pending invitations the current user sent, across accounts.
    //
    listMine(): Promise<InvitationDto[]> {
      return http.get(`${V1}/users/me/invitations/`);
    },

    send(accountId: string, inviteeEmail: string): Promise<null> {
      return http.post(`${V1}/bank-accounts/${accountId}/invite/`, {
        invitee_email: inviteeEmail,
      });
    },

    cancel(accountId: string, token: string): Promise<null> {
      return http.post(
        `${V1}/bank-accounts/${accountId}/invitations/${token}/cancel/`,
      );
    },
  };
}
