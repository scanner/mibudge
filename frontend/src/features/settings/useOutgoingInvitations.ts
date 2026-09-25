//
// `useOutgoingInvitations`: the pending co-owner invitations the user
// sent, across all their accounts.  Feature composable (settings).
//
// Loaded once on mount.  A failed load or cancel sets `error` (the
// server's message when it sent one) and leaves the rest of the
// settings page unaffected.  Cancelling needs no confirmation: the
// owner can simply invite again.
//

// 3rd party imports
//
import { onMounted, ref } from "vue";

// app imports
//
import { api } from "@/api";
import { describeError } from "@/api/errors";
import type { Invitation } from "@/models/invitation";
import { invitationFromDto } from "@/models/invitation";

////////////////////////////////////////////////////////////////////////
//
export function useOutgoingInvitations() {
  const invitations = ref<Invitation[]>([]);
  const cancellingId = ref<string | null>(null);
  const error = ref<string | null>(null);

  onMounted(async () => {
    try {
      invitations.value = (await api.invitations.listMine()).map(invitationFromDto);
    } catch (err) {
      invitations.value = [];
      error.value = describeError(err, "Failed to load your pending invitations.");
    }
  });

  async function cancel(inv: Invitation): Promise<void> {
    cancellingId.value = inv.id;
    error.value = null;
    try {
      await api.invitations.cancel(inv.bankAccountId, inv.token);
      invitations.value = invitations.value.filter((i) => i.id !== inv.id);
    } catch (err) {
      // The row stays; the user can retry.
      error.value = describeError(err, "Failed to cancel the invitation.");
    } finally {
      cancellingId.value = null;
    }
  }

  return { invitations, cancellingId, error, cancel };
}
