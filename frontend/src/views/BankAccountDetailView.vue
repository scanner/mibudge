<script setup lang="ts">
//
// BankAccountDetailView — one bank account: balances, details, owners
// and co-owner invitations, budgets link, funding, and delete.
// (UI_SPEC §4.8)  Route shell over `useBankAccountDetail`,
// `useInviteFlow` and `useFundingRun`; the sections are presentational
// components in `components/bankAccounts/`.
//

// 3rd party imports
//
import { IconChevronRight } from "@tabler/icons-vue";
import { ref } from "vue";
import { useRouter } from "vue-router";

// app imports
//
import BankAccountBalanceGrid from "@/components/bankAccounts/BankAccountBalanceGrid.vue";
import BankAccountDetailsCard from "@/components/bankAccounts/BankAccountDetailsCard.vue";
import BankAccountHeader from "@/components/bankAccounts/BankAccountHeader.vue";
import FundingCard from "@/components/bankAccounts/FundingCard.vue";
import OwnersCard from "@/components/bankAccounts/OwnersCard.vue";
import PendingInvitationsCard from "@/components/bankAccounts/PendingInvitationsCard.vue";
import ConfirmSheet from "@/components/shared/ConfirmSheet.vue";
import { useBankAccountDetail } from "@/features/bankAccounts/useBankAccountDetail";
import { useFundingRun } from "@/features/bankAccounts/useFundingRun";
import { useInviteFlow } from "@/features/bankAccounts/useInviteFlow";
import AppShell from "@/features/shell/AppShell.vue";
import { useAccountContextStore } from "@/stores/accountContext";

////////////////////////////////////////////////////////////////////////
//
const props = defineProps<{ id: string }>();
const router = useRouter();
const ctx = useAccountContextStore();

const detail = useBankAccountDetail(() => props.id);
const { account, bankName, budgetCount, loading, error } = detail;
const invite = useInviteFlow(() => props.id);
const funding = useFundingRun(() => props.id);

const confirmDelete = ref(false);

////////////////////////////////////////////////////////////////////////
//
function viewBudgets() {
  ctx.setActive(props.id);
  router.push({ name: "budgets" });
}

async function onDelete() {
  if (await detail.deleteAccount()) router.push({ name: "account" });
  else confirmDelete.value = false;
}
</script>

<template>
  <AppShell>
    <div v-if="loading" class="mt-8 flex justify-center">
      <span class="text-sm text-secondary">Loading…</span>
    </div>

    <div
      v-else-if="error"
      class="mt-4 rounded-subcard bg-coral-50 px-4 py-3 text-sm text-coral-600"
      role="alert"
    >
      {{ error }}
    </div>

    <div v-else-if="account" class="mx-auto max-w-lg space-y-5 py-4">
      <BankAccountHeader
        v-model:name="detail.editName.value"
        v-model:account-number="detail.editAccountNumber.value"
        :account="account"
        :bank-name="bankName"
        :editing="detail.editing.value"
        :saving="detail.saving.value"
        :name-error="detail.nameError.value"
        @edit="detail.startEdit"
        @save="detail.saveEdit"
        @cancel="detail.cancelEdit"
      />

      <BankAccountBalanceGrid
        :account="account"
        :unallocated="detail.unallocated.value?.balance ?? null"
      />

      <BankAccountDetailsCard
        :account="account"
        :bank-name="bankName"
        :created-date="detail.createdDate.value"
        @edit="detail.startEdit"
      />

      <OwnersCard
        v-model:email="invite.email.value"
        :owners="account.owners"
        :form-open="invite.formOpen.value"
        :sending="invite.sending.value"
        :sent="invite.sent.value"
        :error="invite.error.value"
        @open="invite.open"
        @review="invite.review"
        @close="invite.closeForm"
      />

      <PendingInvitationsCard
        :invitations="invite.invitations.value"
        :cancelling-id="invite.cancellingId.value"
        :can-cancel="invite.canCancel"
        :error="invite.invitationsError.value"
        @cancel="invite.cancelInvitation"
      />

      <!-- Budgets -->
      <section
        class="overflow-hidden rounded-card border border-neutral-200 bg-white"
      >
        <button
          type="button"
          class="flex w-full items-center justify-between px-4 py-3.5 text-left hover:bg-neutral-50"
          @click="viewBudgets"
        >
          <div>
            <div class="text-sm font-medium text-neutral-900">
              Budgets
              <span v-if="budgetCount !== null" class="ml-1.5 text-secondary">
                {{ budgetCount }}
              </span>
            </div>
            <div class="text-xs text-secondary">
              View all budgets for this account
            </div>
          </div>
          <IconChevronRight class="h-4 w-4 flex-none text-neutral-400" />
        </button>
      </section>

      <FundingCard
        :last-posted-through="account.lastPostedThrough"
        :summary="funding.summary.value"
        :auto-funding-enabled="detail.autoFundingEnabled.value"
        :running="funding.running.value"
        :result="funding.result.value"
        :nothing-due="funding.nothingDue.value"
        :next-date="funding.nextDate.value"
        :error="funding.error.value ?? detail.autoFundingError.value"
        @toggle-auto-funding="detail.toggleAutoFunding"
        @run="funding.run"
      />

      <!-- Delete -->
      <section class="pt-2">
        <button
          type="button"
          class="w-full rounded-card border border-coral-400 py-3 text-sm font-medium text-coral-600 hover:bg-coral-50"
          @click="confirmDelete = true"
        >
          Delete account
        </button>
        <p class="mt-2 px-1 text-center text-xs text-neutral-400">
          Deletes all budgets, transactions, and allocations for this account.
        </p>
        <p
          v-if="detail.deleteError.value"
          class="mt-2 text-center text-sm text-coral-600"
          role="alert"
        >
          {{ detail.deleteError.value }}
        </p>
      </section>
    </div>

    <!-- Invite confirmation sheet — step 2 of the invite flow.
         Echoes the email back to the user before committing the send,
         satisfying the UX requirement that the address be confirmed
         before the invitation is created.  Cancelling here returns the
         user to the email-entry form (inviteOpen stays true) so they
         can correct a typo without starting over. -->
    <ConfirmSheet
      :open="invite.confirming.value"
      title="Send co-owner invitation?"
      :message="`Send a co-owner invitation to ${invite.email.value}? They will receive an email with a link to accept or decline.`"
      confirm-label="Send invitation"
      tone="ocean"
      @confirm="invite.send"
      @cancel="invite.confirming.value = false"
    />

    <!-- Delete confirmation sheet -->
    <ConfirmSheet
      :open="confirmDelete"
      title="Delete account?"
      :message="`This will permanently delete &quot;${account?.name}&quot; and all its budgets, transactions, and allocations. This cannot be undone.`"
      confirm-label="Delete account"
      @confirm="onDelete"
      @cancel="confirmDelete = false"
    />
  </AppShell>
</template>
