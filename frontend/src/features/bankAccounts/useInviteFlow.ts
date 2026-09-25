//
// `useInviteFlow`: invite a co-owner to a bank account and manage the
// account's pending invitations.  Feature composable (bankAccounts).
//
// The flow has three steps, mirroring the delete confirmation:
//   1. `open()` shows the email form (resetting any earlier state);
//   2. `review()` checks the address is non-empty and asks for
//      confirmation (`confirming`);
//   3. `send()` posts the invitation, closes the form, shows the
//      success note, and reloads the pending list from the server (for
//      the real token and timestamps).
// A 409 (already an owner, or already invited) gets one message: the
// user's next step is the same either way.
//
// `cancelInvitation()` removes the row once the server confirms.
//

// 3rd party imports
//
import { computed, ref } from "vue";

// app imports
//
import { api } from "@/api";
import { useFormErrors } from "@/composables/useFormErrors";
import { useResource } from "@/composables/useResource";
import type { Invitation } from "@/models/invitation";
import { invitationFromDto } from "@/models/invitation";
import { useSessionStore } from "@/stores/session";

////////////////////////////////////////////////////////////////////////
//
export function useInviteFlow(accountId: () => string) {
  const session = useSessionStore();

  const pending = useResource(accountId, async (id: string) =>
    (await api.invitations.listForAccount(id)).map(invitationFromDto),
  );
  const removed = ref(new Set<string>());
  const invitations = computed(() =>
    (pending.data.value ?? []).filter((inv) => !removed.value.has(inv.id)),
  );

  ////////////////////////////////////////////////////////////////////
  //
  const formOpen = ref(false);
  const email = ref("");
  const confirming = ref(false);
  const sending = ref(false);
  const sent = ref(false);
  const cancellingId = ref<string | null>(null);
  const errors = useFormErrors();

  function open(): void {
    formOpen.value = true;
    email.value = "";
    errors.clear();
    sent.value = false;
  }

  function closeForm(): void {
    formOpen.value = false;
    errors.clear();
  }

  function review(): void {
    errors.clear();
    if (!email.value.trim()) {
      errors.setFormError("Email address is required.");
      return;
    }
    confirming.value = true;
  }

  async function send(): Promise<void> {
    confirming.value = false;
    sending.value = true;
    errors.clear();
    try {
      await api.invitations.send(accountId(), email.value.trim().toLowerCase());
      formOpen.value = false;
      email.value = "";
      sent.value = true;
      removed.value = new Set();
      await pending.reload();
    } catch (err) {
      errors.setError(err, {
        fallback: "Failed to send invitation.",
        inlineFields: false,
        statusMessages: {
          409: "A pending invitation for this address already exists, or they are already an owner.",
        },
      });
    } finally {
      sending.value = false;
    }
  }

  ////////////////////////////////////////////////////////////////////
  //
  // Only the sender may cancel (the server enforces it too).
  //
  function canCancel(inv: Invitation): boolean {
    return inv.invitedBy === session.user?.email;
  }

  async function cancelInvitation(inv: Invitation): Promise<void> {
    cancellingId.value = inv.id;
    try {
      await api.invitations.cancel(accountId(), inv.token);
      removed.value = new Set([...removed.value, inv.id]);
    } catch {
      // The row stays; the user can retry.
    } finally {
      cancellingId.value = null;
    }
  }

  return {
    invitations,
    formOpen,
    email,
    confirming,
    sending,
    sent,
    error: errors.formError,
    cancellingId,
    open,
    closeForm,
    review,
    send,
    canCancel,
    cancelInvitation,
  };
}
