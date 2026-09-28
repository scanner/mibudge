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
import BaseButton from "@/components/base/BaseButton.vue";
import BaseSectionHeader from "@/components/base/BaseSectionHeader.vue";
import BaseListRow from "@/components/base/BaseListRow.vue";

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
  return formatInstantDate(iso, "date");
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
    <BaseSectionHeader title="Pending invitations" card />
    <ul>
      <BaseListRow
        v-for="inv in invitations"
        as="li"
        class="justify-between"
        :key="inv.id"
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
        <BaseButton
          v-if="canCancel(inv)"
          variant="link-danger"
          size="sm"
          :loading="cancellingId === inv.id"
          @click="emit('cancel', inv)"
        >
          {{ cancellingId === inv.id ? "Cancelling…" : "Cancel" }}
        </BaseButton>
      </BaseListRow>
    </ul>
    <p v-if="error" class="px-4 pb-3 text-meta text-danger-fg" role="alert">
      {{ error }}
    </p>
  </section>
</template>
