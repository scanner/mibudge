//
// `useOutgoingInvitations`: the pending co-owner invitations the user
// sent, across all their accounts.  Feature composable (settings).
//
// Loaded once on mount.  A load failure leaves the list empty so the
// rest of the settings page is unaffected.  Cancelling needs no
// confirmation: the owner can simply invite again.
//

// 3rd party imports
//
import { onMounted, ref } from "vue";

// app imports
//
import { api } from "@/api";
import type { Invitation } from "@/models/invitation";
import { invitationFromDto } from "@/models/invitation";

////////////////////////////////////////////////////////////////////////
//
export function useOutgoingInvitations() {
  const invitations = ref<Invitation[]>([]);
  const cancellingId = ref<string | null>(null);

  onMounted(async () => {
    try {
      invitations.value = (await api.invitations.listMine()).map(invitationFromDto);
    } catch {
      invitations.value = [];
    }
  });

  async function cancel(inv: Invitation): Promise<void> {
    cancellingId.value = inv.id;
    try {
      await api.invitations.cancel(inv.bankAccountId, inv.token);
      invitations.value = invitations.value.filter((i) => i.id !== inv.id);
    } catch {
      // The row stays; the user can retry.
    } finally {
      cancellingId.value = null;
    }
  }

  return { invitations, cancellingId, cancel };
}
