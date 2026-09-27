<script setup lang="ts">
//
// PendingInvitationsCard — an account's pending co-owner invitations.
// Presentational: `canCancel` decides which rows show Cancel (only the
// sender's); emits `cancel` with the invitation.  Renders nothing when
// there are no invitations and no `error`.
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
  error?: string | null;
}>();

const emit = defineEmits<{ (e: "cancel", inv: Invitation): void }>();

function fmtDate(iso: string): string {
  return formatInstantDate(iso, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
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
    v-if="invitations.length > 0 || error"
    class="overflow-hidden rounded-card border border-border bg-surface"
  >
    <h2
      class="border-b border-border-subtle px-4 py-3 text-overline uppercase text-fg-muted"
    >
      Pending invitations
    </h2>
    <ul class="divide-y divide-border-subtle">
      <li
        v-for="inv in invitations"
        :key="inv.id"
        class="flex items-center justify-between px-4 py-3"
      >
        <div>
          <p class="text-body-sm text-fg">{{ inv.inviteeEmail }}</p>
          <p class="mt-0.5 text-meta text-fg-muted">
            Expires {{ fmtDate(inv.expiresAt) }}
          </p>
        </div>
        <!-- Only show Cancel for invitations sent by the current user.
             The backend enforces the same rule (403 if not the sender),
             but hiding the button for others avoids a confusing error. -->
        <button
          v-if="canCancel(inv)"
          type="button"
          :disabled="cancellingId === inv.id"
          class="text-meta font-medium text-danger-fg hover:text-danger-solid-hover disabled:opacity-50"
          @click="emit('cancel', inv)"
        >
          {{ cancellingId === inv.id ? "Cancelling…" : "Cancel" }}
        </button>
      </li>
    </ul>
    <p v-if="error" class="px-4 pb-3 text-meta text-danger-fg" role="alert">
      {{ error }}
    </p>
  </section>
</template>
