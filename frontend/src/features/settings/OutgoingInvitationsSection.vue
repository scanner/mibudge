<script setup lang="ts">
//
// OutgoingInvitationsSection — the co-owner invitations the user sent,
// across all their accounts, with Cancel.  Feature component
// (settings); data lives in `useOutgoingInvitations`.  Renders nothing
// when there are none.
//

// app imports
//
import { formatInstantDate } from "@/domain/dates";
import { useOutgoingInvitations } from "./useOutgoingInvitations";

////////////////////////////////////////////////////////////////////////
//
const { invitations, cancellingId, cancel } = useOutgoingInvitations();

function shortDate(iso: string): string {
  return formatInstantDate(iso, { month: "short", day: "numeric", year: "numeric" });
}
</script>

<template>
  <!-- ── Outgoing invitations ───────────────────────────────────── -->
  <!-- Only rendered when there is at least one pending invitation so
       the section does not appear at all for users who have never
       invited anyone or whose invitations have all been resolved. -->
  <template v-if="invitations.length > 0">
    <h1 class="mb-5 mt-10 text-[22px] font-medium text-neutral-900">Pending invitations</h1>

    <section>
      <div class="rounded-card border border-neutral-200 bg-white">
        <ul class="divide-y divide-neutral-100">
          <li
            v-for="inv in invitations"
            :key="inv.id"
            class="flex items-start justify-between px-4 py-3"
          >
            <div>
              <!-- Account name links the invitation back to its
                   context; the invitee email is the primary identifier. -->
              <p class="text-xs font-medium uppercase tracking-wider text-secondary">
                {{ inv.bankAccountName }}
              </p>
              <p class="mt-0.5 text-sm text-neutral-900">{{ inv.inviteeEmail }}</p>
              <p class="mt-0.5 text-xs text-secondary">
                Expires
                {{ shortDate(inv.expiresAt) }}
              </p>
            </div>
            <button
              type="button"
              :disabled="cancellingId === inv.id"
              class="mt-0.5 flex-none text-xs font-medium text-coral-600 hover:text-coral-700 disabled:opacity-50"
              @click="cancel(inv)"
            >
              {{ cancellingId === inv.id ? "Cancelling…" : "Cancel" }}
            </button>
          </li>
        </ul>
      </div>
    </section>
  </template>
</template>
