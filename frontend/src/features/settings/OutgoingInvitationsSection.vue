<script setup lang="ts">
//
// OutgoingInvitationsSection — the co-owner invitations the user sent,
// across all their accounts, with Cancel.  Feature component
// (settings); data lives in `useOutgoingInvitations`.  Renders nothing
// when there are none and nothing failed.
//

// app imports
//
import { formatInstantDate } from "@/domain/dates";
import { useOutgoingInvitations } from "./useOutgoingInvitations";
import BaseButton from "@/components/base/BaseButton.vue";
import BaseSectionHeader from "@/components/base/BaseSectionHeader.vue";
import BasePageHeader from "@/components/base/BasePageHeader.vue";
import BaseListRow from "@/components/base/BaseListRow.vue";

////////////////////////////////////////////////////////////////////////
//
const { invitations, cancellingId, error, cancel } = useOutgoingInvitations();

function shortDate(iso: string): string {
  return formatInstantDate(iso, "date");
}
</script>

<template>
  <!-- ── Outgoing invitations ───────────────────────────────────── -->
  <!-- Only rendered when there is at least one pending invitation so
       the section does not appear at all for users who have never
       invited anyone or whose invitations have all been resolved. -->
  <template v-if="invitations.length > 0 || error">
    <BasePageHeader title="Pending invitations" class="mt-10" />

    <section>
      <p v-if="error" class="mb-2 text-body-sm text-danger-fg" role="alert">
        {{ error }}
      </p>
      <div
        v-if="invitations.length > 0"
        class="rounded-card border border-border bg-surface"
      >
        <ul>
          <BaseListRow
            v-for="inv in invitations"
            as="li"
            align="start"
            class="justify-between"
            :key="inv.id"
          >
            <div>
              <!-- Account name links the invitation back to its
                   context; the invitee email is the primary identifier. -->
              <BaseSectionHeader :title="inv.bankAccountName" as="div" />
              <p class="mt-0.5 text-body-sm text-fg">
                {{ inv.inviteeEmail }}
              </p>
              <p class="mt-0.5 text-meta text-fg-muted">
                Expires
                {{ shortDate(inv.expiresAt) }}
              </p>
            </div>
            <BaseButton
              variant="link-danger"
              size="sm"
              :loading="cancellingId === inv.id"
              class="mt-0.5 flex-none"
              @click="cancel(inv)"
            >
              {{ cancellingId === inv.id ? "Cancelling…" : "Cancel" }}
            </BaseButton>
          </BaseListRow>
        </ul>
      </div>
    </section>
  </template>
</template>
