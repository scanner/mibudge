<script setup lang="ts">
//
// PendingInvitationsCard — an account's pending co-owner invitations.
// Presentational: `canCancel` decides which rows show Cancel (only the
// sender's); emits `cancel` with the invitation.  Renders nothing when
// there are no invitations.
//

// app imports
//
import { formatInstantDate } from "@/domain/dates";
import type { Invitation } from "@/models/invitation";

////////////////////////////////////////////////////////////////////////
//
defineProps<{
  invitations: Invitation[];
  cancellingId: string | null;
  canCancel: (inv: Invitation) => boolean;
}>();

const emit = defineEmits<{ (e: "cancel", inv: Invitation): void }>();

function fmtDate(iso: string): string {
  return formatInstantDate(iso, { month: "short", day: "numeric", year: "numeric" });
}
</script>

<template>
  <!-- Pending invitations
       Shown as a separate section (not merged into Owners) because
       the pending list has its own actions (Cancel) and lifecycle,
       and mixing it into the owners list would make the UI harder to
       scan.  The section is only rendered when there is at least one
       pending invitation; once all are accepted/declined/cancelled it
       disappears automatically. -->
  <section
    v-if="invitations.length > 0"
    class="overflow-hidden rounded-card border border-neutral-200 bg-white"
  >
    <h2
      class="border-b border-neutral-100 px-4 py-3 text-[11px] font-semibold uppercase tracking-wider text-secondary"
    >
      Pending invitations
    </h2>
    <ul class="divide-y divide-neutral-100">
      <li
        v-for="inv in invitations"
        :key="inv.id"
        class="flex items-center justify-between px-4 py-3"
      >
        <div>
          <p class="text-sm text-neutral-900">{{ inv.inviteeEmail }}</p>
          <p class="mt-0.5 text-xs text-secondary">Expires {{ fmtDate(inv.expiresAt) }}</p>
        </div>
        <!-- Only show Cancel for invitations sent by the current user.
             The backend enforces the same rule (403 if not the sender),
             but hiding the button for others avoids a confusing error. -->
        <button
          v-if="canCancel(inv)"
          type="button"
          :disabled="cancellingId === inv.id"
          class="text-xs font-medium text-coral-600 hover:text-coral-700 disabled:opacity-50"
          @click="emit('cancel', inv)"
        >
          {{ cancellingId === inv.id ? "Cancelling…" : "Cancel" }}
        </button>
      </li>
    </ul>
  </section>
</template>
