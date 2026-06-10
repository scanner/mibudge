<script setup lang="ts">
//
// BankAccountDetailView — read-only hero grid, details, owners, budget
// count, inline name edit, delete with confirmation, and co-owner invitation.
// (UI_SPEC §4.8, /app/account/bank-accounts/:id/)
//
// Invite flow overview
// --------------------
// The co-owner invite is a two-step action deliberately modelled on the
// existing name-edit and delete-confirmation patterns already in this view:
//
//   1. Owner clicks "Invite co-owner" → openInvite() shows the inline form.
//   2. Owner enters an email and clicks "Review" → reviewInvite() validates
//      and opens the ConfirmSheet asking "Send invitation to <email>?".
//   3. Owner confirms → doSendInvite() POSTs to the backend, then reloads
//      the pending-invitations list from the server.
//
// Cancellation (doCancelInvitation) is an optimistic removal: the row
// disappears immediately and is only restored if the backend returns an
// error (rare; the most likely failure is a network blip).
//
// All invite/cancel state is local to this component.  There is no Pinia
// store for invitations because the data is only ever needed here and on
// the AccountSettingsView; each view loads its own slice independently.
//

// 3rd party imports
//
import { IconChevronRight, IconPencil } from "@tabler/icons-vue";
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";

// app imports
//
import ConfirmSheet from "@/components/shared/ConfirmSheet.vue";
import MoneyAmount from "@/components/shared/MoneyAmount.vue";
import AppShell from "@/components/layout/AppShell.vue";
import {
  deleteBankAccount,
  fundingSummary,
  getBankAccount,
  runFunding,
  updateBankAccount,
  type FundingRunResult,
} from "@/api/bankAccounts";
import { cancelInvitation, listAccountInvitations, sendInvitation } from "@/api/invitations";
import { ApiError } from "@/api/client";
import type { BankAccount, BankAccountInvitation, FundingSummary } from "@/types/api";
import { getBank } from "@/api/banks";
import { listBudgets } from "@/api/budgets";
import { useAccountContextStore } from "@/stores/accountContext";
import { useAuthStore } from "@/stores/auth";
import { useBudgetsStore } from "@/stores/budgets";

////////////////////////////////////////////////////////////////////////
//
const props = defineProps<{ id: string }>();

const router = useRouter();
const ctx = useAccountContextStore();
const budgetsStore = useBudgetsStore();
const authStore = useAuthStore();

const account = ref<BankAccount | null>(null);
const bankName = ref<string | null>(null);
const budgetCount = ref<number | null>(null);
const loading = ref(true);
const error = ref<string | null>(null);

// Inline edit state (name + account number).
const editing = ref(false);
const editName = ref("");
const editAccountNumber = ref("");
const saving = ref(false);
const nameError = ref<string | null>(null);

// Delete confirmation.
const confirmDelete = ref(false);
const deleting = ref(false);

// Invite co-owner state.
//
// invitations     — current list of PENDING invitations for this account,
//                   loaded on mount alongside the rest of the page data.
// inviteOpen      — controls visibility of the inline email-entry form.
// inviteConfirm   — controls the ConfirmSheet shown before the API call.
// inviteSending   — true while the POST /invite/ is in-flight; disables
//                   the Send button so the user cannot double-submit.
// inviteSuccess   — transient flag that shows the "Invitation sent" banner
//                   after a successful send; cleared when the form reopens.
// cancellingId    — the UUID of the invitation currently being cancelled,
//                   used to show a spinner on that specific row's button.
const invitations = ref<BankAccountInvitation[]>([]);
const inviteOpen = ref(false);
const inviteEmail = ref("");
const inviteConfirm = ref(false);
const inviteSending = ref(false);
const inviteError = ref<string | null>(null);
const inviteSuccess = ref(false);
const cancellingId = ref<string | null>(null);

// Run-funding state.
const funding = ref(false);
const fundingResult = ref<FundingRunResult | null>(null);
const fundingNextDate = ref<string | null>(null);
const fundingError = ref<string | null>(null);
const fundingSummaryData = ref<FundingSummary | null>(null);

const nothingDue = computed(
  () =>
    fundingResult.value !== null &&
    fundingResult.value.transfers === 0 &&
    fundingResult.value.warnings.length === 0 &&
    fundingResult.value.skipped_budgets.length === 0,
);

async function triggerFunding() {
  funding.value = true;
  fundingResult.value = null;
  fundingNextDate.value = null;
  fundingError.value = null;
  try {
    fundingResult.value = await runFunding(props.id);
    // Refresh account balances and next-event date in parallel.
    const [acct, summary] = await Promise.all([
      getBankAccount(props.id),
      fundingSummary(props.id).catch(() => null as FundingSummary | null),
    ]);
    account.value = acct;
    if (acct.unallocated_budget) {
      budgetsStore.fetchOne(acct.unallocated_budget);
    }
    fundingSummaryData.value = summary;
    fundingNextDate.value = summary?.schedules[0]?.next_date ?? null;
  } catch (err) {
    fundingError.value = err instanceof Error ? err.message : "Funding run failed.";
  } finally {
    funding.value = false;
  }
}

////////////////////////////////////////////////////////////////////////
//
const ACCOUNT_TYPE_LABELS: Record<string, string> = {
  C: "Checking",
  S: "Savings",
  X: "Credit card",
};

const unallocated = computed(() => {
  if (!account.value?.unallocated_budget) return null;
  return budgetsStore.byId(account.value.unallocated_budget);
});

const createdDate = computed(() => {
  if (!account.value) return "";
  return new Date(account.value.created_at).toLocaleDateString(undefined, {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
});

////////////////////////////////////////////////////////////////////////
//
onMounted(async () => {
  loading.value = true;
  error.value = null;
  try {
    const [acct, budgetsPage, summary, invites] = await Promise.all([
      getBankAccount(props.id),
      listBudgets({ bank_account: props.id }),
      fundingSummary(props.id).catch(() => null as FundingSummary | null),
      listAccountInvitations(props.id).catch(() => [] as BankAccountInvitation[]),
    ]);
    invitations.value = invites;
    fundingSummaryData.value = summary;
    account.value = acct;
    editName.value = acct.name;

    // Count user-facing budgets (exclude unallocated and auto-created fill-up goals).
    budgetCount.value = budgetsPage.results.filter(
      (b) => b.id !== acct.unallocated_budget && b.budget_type !== "A",
    ).length;

    // Load unallocated balance.
    if (acct.unallocated_budget && !budgetsStore.byId(acct.unallocated_budget)) {
      budgetsStore.fetchOne(acct.unallocated_budget);
    }

    // Resolve bank name.
    if (acct.bank) {
      try {
        const bank = await getBank(acct.bank);
        bankName.value = bank.name;
      } catch {
        bankName.value = null;
      }
    }
  } catch (err) {
    error.value = err instanceof Error ? err.message : "Failed to load account.";
  } finally {
    loading.value = false;
  }
});

////////////////////////////////////////////////////////////////////////
//
function startEdit() {
  if (!account.value) return;
  editName.value = account.value.name;
  editAccountNumber.value = account.value.account_number ?? "";
  editing.value = true;
  nameError.value = null;
}

function cancelEdit() {
  editing.value = false;
  nameError.value = null;
}

async function saveName() {
  if (!account.value || !editName.value.trim()) {
    nameError.value = "Name is required.";
    return;
  }
  saving.value = true;
  nameError.value = null;
  try {
    const body: Partial<typeof account.value> = { name: editName.value.trim() };
    if (editAccountNumber.value.trim() !== (account.value.account_number ?? "")) {
      body.account_number = editAccountNumber.value.trim() || null;
    }
    const updated = await updateBankAccount(props.id, body);
    account.value = updated;
    editing.value = false;
    await ctx.refresh();
  } catch (err) {
    nameError.value = err instanceof Error ? err.message : "Failed to save.";
  } finally {
    saving.value = false;
  }
}

////////////////////////////////////////////////////////////////////////
//
async function toggleAutoFunding(): Promise<void> {
  if (!account.value) return;
  const prev = account.value.auto_funding_enabled;
  account.value.auto_funding_enabled = !prev;
  try {
    const updated = await updateBankAccount(props.id, {
      auto_funding_enabled: !prev,
    });
    account.value = updated;
  } catch {
    account.value.auto_funding_enabled = prev;
  }
}

////////////////////////////////////////////////////////////////////////
// Invite co-owner — three-function flow
//
// The flow is deliberately split into three small functions (open → review
// → send) rather than one large async handler.  This mirrors the delete
// flow (startDelete → confirmDelete sheet → deleteAccount) and keeps each
// step testable in isolation: open resets UI state, review validates and
// opens the confirmation dialog, doSendInvite performs the async work.

// openInvite — enter step 1 of the invite flow.
//
// Resets all invite-related state so that reopening the form after a
// previous error or success always starts clean.
function openInvite() {
  inviteOpen.value = true;
  inviteEmail.value = "";
  inviteError.value = null;
  inviteSuccess.value = false;
}

// cancelInviteForm — dismiss the invite form without sending anything.
//
// Called by the "Cancel" button inside the inline form, and also when
// the ConfirmSheet's cancel handler fires (the user backed out of the
// confirmation dialog).
function cancelInviteForm() {
  inviteOpen.value = false;
  inviteError.value = null;
}

// reviewInvite — validate the email and open the confirmation dialog.
//
// This is the bridge between the text-input step and the ConfirmSheet.
// Client-side validation here is intentionally minimal (just "is it
// non-empty?") — the backend will reject an already-used address or a
// malformed email with a descriptive error that doSendInvite surfaces.
function reviewInvite() {
  inviteError.value = null;
  if (!inviteEmail.value.trim()) {
    inviteError.value = "Email address is required.";
    return;
  }
  inviteConfirm.value = true;
}

// doSendInvite — POST the invitation once the user has confirmed.
//
// Called by the ConfirmSheet's @confirm event.  On success the inline
// form closes, the pending-invitations list refreshes from the server
// (rather than appending speculatively, to get the real token and
// timestamps), and a transient success banner appears.
//
// HTTP 409 has two distinct causes the backend may return: the address
// is already an owner, or a pending invitation already exists.  Both
// are grouped into a single user-facing message because the action the
// user should take is the same either way (contact the person by other
// means or wait for the existing invitation to expire).
async function doSendInvite() {
  inviteConfirm.value = false;
  inviteSending.value = true;
  inviteError.value = null;
  try {
    await sendInvitation(props.id, inviteEmail.value.trim().toLowerCase());
    inviteOpen.value = false;
    inviteEmail.value = "";
    inviteSuccess.value = true;
    // Reload from server so the new row has real server-assigned timestamps
    // and the token needed for the cancel action.
    invitations.value = await listAccountInvitations(props.id);
  } catch (err) {
    if (err instanceof ApiError && err.status === 409) {
      inviteError.value =
        "A pending invitation for this address already exists, or they are already an owner.";
    } else {
      inviteError.value = err instanceof Error ? err.message : "Failed to send invitation.";
    }
  } finally {
    inviteSending.value = false;
  }
}

////////////////////////////////////////////////////////////////////////
//
// doCancelInvitation — withdraw a pending invitation before it is accepted.
//
// Uses an optimistic removal: the row disappears immediately from the UI
// and is only put back if the backend returns an error.  This keeps the
// interaction snappy for the common case (successful cancel) without
// requiring a loading spinner on every row.
//
// cancellingId tracks which row is in-flight so the template can disable
// that row's button while the request is pending, preventing double-clicks
// from racing each other.
async function doCancelInvitation(inv: BankAccountInvitation) {
  cancellingId.value = inv.id;
  try {
    await cancelInvitation(props.id, inv.token);
    invitations.value = invitations.value.filter((i) => i.id !== inv.id);
  } catch {
    // Silently leave the list unchanged on error.  The user can retry; a
    // toast or persistent error would be disproportionate for this action.
  } finally {
    cancellingId.value = null;
  }
}

////////////////////////////////////////////////////////////////////////
//
// fmtDate — format an ISO datetime string as a short locale date.
//
// Used inline rather than as a shared utility because date formatting
// needs differ per view and a shared formatter would need configuration
// options that would make it more complex than just calling toLocaleDateString
// directly.  See task-mibudge-spa-architecture-doc for the known-gap note
// on this.
function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

async function deleteAccount() {
  deleting.value = true;
  try {
    await deleteBankAccount(props.id);
    await ctx.refresh();
    // If we deleted the active account, switch to first remaining.
    if (ctx.activeBankAccountId === props.id) {
      ctx.setActive(ctx.accounts[0]?.id ?? null);
    }
    router.push("/account/");
  } catch {
    deleting.value = false;
    confirmDelete.value = false;
  }
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
      <!-- Inline name editor -->
      <div v-if="editing" class="rounded-card border border-ocean-400 bg-white px-4 py-4">
        <label class="mb-1.5 block text-sm font-medium text-neutral-700" for="edit-name">
          Account name
        </label>
        <input
          id="edit-name"
          v-model="editName"
          type="text"
          class="w-full rounded-subcard border border-neutral-200 px-3 py-2.5 text-sm text-neutral-900 focus:border-ocean-400 focus:outline-none focus:ring-1 focus:ring-ocean-400"
          @keydown.enter="saveName"
          @keydown.escape="cancelEdit"
        />
        <label
          class="mb-1.5 mt-3 block text-sm font-medium text-neutral-700"
          for="edit-account-number"
        >
          Account number
        </label>
        <input
          id="edit-account-number"
          v-model="editAccountNumber"
          type="text"
          inputmode="numeric"
          class="w-full rounded-subcard border border-neutral-200 px-3 py-2.5 font-mono text-sm text-neutral-900 focus:border-ocean-400 focus:outline-none focus:ring-1 focus:ring-ocean-400"
          @keydown.enter="saveName"
          @keydown.escape="cancelEdit"
        />
        <p v-if="nameError" class="mt-1 text-xs text-coral-600">{{ nameError }}</p>
        <div class="mt-3 flex gap-2">
          <button
            type="button"
            :disabled="saving"
            class="flex-1 rounded-subcard bg-ocean-400 py-2 text-sm font-medium text-white hover:bg-ocean-600 disabled:opacity-50"
            @click="saveName"
          >
            {{ saving ? "Saving…" : "Save" }}
          </button>
          <button
            type="button"
            class="flex-1 rounded-subcard border border-neutral-200 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-50"
            @click="cancelEdit"
          >
            Cancel
          </button>
        </div>
      </div>

      <!-- Account name heading (non-editing) -->
      <div v-else>
        <div class="flex items-center gap-2">
          <h1 class="text-[22px] font-medium text-neutral-900">{{ account.name }}</h1>
          <button
            type="button"
            class="flex h-7 w-7 flex-none items-center justify-center rounded-full text-neutral-400 hover:bg-neutral-100 hover:text-neutral-600"
            aria-label="Edit account"
            @click="startEdit"
          >
            <IconPencil class="h-4 w-4" />
          </button>
        </div>
        <p class="text-sm text-secondary">
          {{ ACCOUNT_TYPE_LABELS[account.account_type] ?? account.account_type }}
          <template v-if="bankName"> · {{ bankName }}</template>
        </p>
      </div>

      <!-- Hero balance grid (2×2) -->
      <section class="grid grid-cols-2 gap-3">
        <div class="rounded-card border border-neutral-200 bg-white px-4 py-3">
          <div class="mb-0.5 text-[11px] font-semibold uppercase tracking-wider text-secondary">
            Posted balance
          </div>
          <MoneyAmount
            :amount="account.posted_balance"
            :currency="account.posted_balance_currency"
            size="md"
          />
        </div>
        <div class="rounded-card border border-neutral-200 bg-white px-4 py-3">
          <div class="mb-0.5 text-[11px] font-semibold uppercase tracking-wider text-secondary">
            Available balance
          </div>
          <MoneyAmount
            :amount="account.available_balance"
            :currency="account.available_balance_currency"
            size="md"
          />
        </div>
        <div class="rounded-card border border-neutral-200 bg-white px-4 py-3">
          <div class="mb-0.5 text-[11px] font-semibold uppercase tracking-wider text-secondary">
            Unallocated
          </div>
          <MoneyAmount
            v-if="unallocated"
            :amount="unallocated.balance"
            :currency="unallocated.balance_currency"
            size="md"
            :coloured="false"
          />
          <span v-else class="font-mono text-[15px] font-medium text-secondary">—</span>
        </div>
        <div class="rounded-card border border-neutral-200 bg-white px-4 py-3">
          <div class="mb-0.5 text-[11px] font-semibold uppercase tracking-wider text-secondary">
            Currency
          </div>
          <span class="font-mono text-[15px] font-medium text-neutral-900">
            {{ account.currency }}
          </span>
        </div>
      </section>

      <!-- Details -->
      <section class="overflow-hidden rounded-card border border-neutral-200 bg-white">
        <h2
          class="border-b border-neutral-100 px-4 py-3 text-[11px] font-semibold uppercase tracking-wider text-secondary"
        >
          Details
        </h2>
        <dl class="divide-y divide-neutral-100">
          <div class="flex items-center justify-between px-4 py-3">
            <dt class="text-sm text-secondary">Account number</dt>
            <dd class="flex items-center gap-2">
              <span class="font-mono text-sm text-neutral-900">
                {{ account.account_number ? `····${account.account_number.slice(-4)}` : "—" }}
              </span>
              <button
                type="button"
                class="flex h-6 w-6 flex-none items-center justify-center rounded-full text-neutral-400 hover:bg-neutral-100 hover:text-neutral-600"
                aria-label="Edit account number"
                @click="startEdit"
              >
                <IconPencil class="h-3.5 w-3.5" />
              </button>
            </dd>
          </div>
          <div class="flex items-center justify-between px-4 py-3">
            <dt class="text-sm text-secondary">Bank</dt>
            <dd class="text-sm text-neutral-900">{{ bankName ?? "—" }}</dd>
          </div>
          <div class="flex items-center justify-between px-4 py-3">
            <dt class="text-sm text-secondary">Created</dt>
            <dd class="text-sm text-neutral-900">{{ createdDate }}</dd>
          </div>
        </dl>
      </section>

      <!-- Owners + invite form
           The invite form lives inside this section so it visually belongs
           with the owners list.  The two-step flow (enter email → confirm
           in ConfirmSheet) keeps the destructive-action confirmation
           pattern consistent with the delete flow below. -->
      <section class="overflow-hidden rounded-card border border-neutral-200 bg-white">
        <div class="flex items-center justify-between border-b border-neutral-100 px-4 py-3">
          <h2 class="text-[11px] font-semibold uppercase tracking-wider text-secondary">Owners</h2>
          <button
            v-if="!inviteOpen"
            type="button"
            class="text-xs font-medium text-ocean-600 hover:text-ocean-700"
            @click="openInvite"
          >
            + Invite co-owner
          </button>
        </div>

        <!-- Current owners list -->
        <ul class="divide-y divide-neutral-100">
          <li
            v-for="owner in account.owners"
            :key="owner"
            class="px-4 py-3 text-sm text-neutral-900"
          >
            {{ owner }}
          </li>
          <li v-if="!account.owners?.length" class="px-4 py-3 text-sm text-neutral-400">—</li>
        </ul>

        <!-- Inline invite form — step 1: enter the email address.
             Appears below the owner list when inviteOpen is true.
             The "Review" button triggers client-side validation and then
             opens the ConfirmSheet for step 2 rather than sending directly,
             giving the user a chance to double-check the address. -->
        <div v-if="inviteOpen" class="border-t border-neutral-100 px-4 py-4">
          <label class="mb-1.5 block text-sm font-medium text-neutral-700" for="invite-email">
            Email address to invite
          </label>
          <input
            id="invite-email"
            v-model="inviteEmail"
            type="email"
            autocomplete="email"
            placeholder="colleague@example.com"
            class="w-full rounded-subcard border border-neutral-200 px-3 py-2.5 text-sm text-neutral-900 focus:border-ocean-400 focus:outline-none focus:ring-1 focus:ring-ocean-400"
            @keydown.enter="reviewInvite"
            @keydown.escape="cancelInviteForm"
          />
          <p v-if="inviteError" class="mt-1 text-xs text-coral-600">{{ inviteError }}</p>
          <div class="mt-3 flex gap-2">
            <button
              type="button"
              :disabled="inviteSending"
              class="flex-1 rounded-subcard bg-ocean-400 py-2 text-sm font-medium text-white hover:bg-ocean-600 disabled:opacity-50"
              @click="reviewInvite"
            >
              {{ inviteSending ? "Sending…" : "Review" }}
            </button>
            <button
              type="button"
              class="flex-1 rounded-subcard border border-neutral-200 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-50"
              @click="cancelInviteForm"
            >
              Cancel
            </button>
          </div>
        </div>

        <!-- Success banner shown after a successful invite send.
             Displayed inside the Owners card so it is contextually near
             the action that triggered it. -->
        <div
          v-if="inviteSuccess && !inviteOpen"
          class="border-t border-neutral-100 px-4 py-3 text-sm text-mint-600"
        >
          Invitation sent.
        </div>
      </section>

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
              <p class="text-sm text-neutral-900">{{ inv.invitee_email }}</p>
              <p class="mt-0.5 text-xs text-secondary">Expires {{ fmtDate(inv.expires_at) }}</p>
            </div>
            <!-- Only show Cancel for invitations sent by the current user.
                 The backend enforces the same rule (403 if not the sender),
                 but hiding the button for others avoids a confusing error. -->
            <button
              v-if="inv.invited_by === authStore.user?.email"
              type="button"
              :disabled="cancellingId === inv.id"
              class="text-xs font-medium text-coral-600 hover:text-coral-700 disabled:opacity-50"
              @click="doCancelInvitation(inv)"
            >
              {{ cancellingId === inv.id ? "Cancelling…" : "Cancel" }}
            </button>
          </li>
        </ul>
      </section>

      <!-- Budgets -->
      <section class="overflow-hidden rounded-card border border-neutral-200 bg-white">
        <button
          type="button"
          class="flex w-full items-center justify-between px-4 py-3.5 text-left hover:bg-neutral-50"
          @click="
            ctx.setActive(props.id);
            router.push('/budgets/');
          "
        >
          <div>
            <div class="text-sm font-medium text-neutral-900">
              Budgets
              <span v-if="budgetCount !== null" class="ml-1.5 text-secondary">
                {{ budgetCount }}
              </span>
            </div>
            <div class="text-xs text-secondary">View all budgets for this account</div>
          </div>
          <IconChevronRight class="h-4 w-4 flex-none text-neutral-400" />
        </button>
      </section>

      <!-- Funding -->
      <section class="overflow-hidden rounded-card border border-neutral-200 bg-white">
        <h2
          class="border-b border-neutral-100 px-4 py-3 text-[11px] font-semibold uppercase tracking-wider text-secondary"
        >
          Funding
        </h2>
        <div class="px-4 py-3 space-y-3">
          <div class="flex items-center justify-between text-sm">
            <span class="text-secondary">Data current through</span>
            <span class="font-mono text-neutral-900">
              {{ account.last_posted_through ?? "—" }}
            </span>
          </div>
          <p class="text-xs text-secondary">
            After importing transactions and finishing allocations, run the funding engine to move
            money into budgets based on their schedules.
          </p>
          <div
            v-if="
              fundingSummaryData &&
              fundingSummaryData.total_amount !== '0' &&
              fundingSummaryData.total_amount !== '0.00'
            "
            class="rounded-subcard border border-ocean-200 bg-ocean-50 px-3 py-2 text-xs text-ocean-700"
          >
            Next event:
            <MoneyAmount
              :amount="fundingSummaryData.total_amount"
              :currency="fundingSummaryData.currency"
              size="sm"
              class="font-medium"
            />
            <template
              v-if="
                fundingSummaryData.schedules.length > 0 && fundingSummaryData.schedules[0].next_date
              "
            >
              on {{ fundingSummaryData.schedules[0].next_date }}
            </template>
            <template v-if="fundingSummaryData.schedules.length > 1">
              across {{ fundingSummaryData.schedules.length }} schedules
            </template>
          </div>
          <!-- Automatic funding toggle -->
          <label class="flex cursor-pointer items-center justify-between">
            <div>
              <p class="text-sm text-neutral-900">Automatic funding</p>
              <p class="mt-0.5 text-xs text-secondary">
                Run funding events on a schedule. Disable to fund manually only.
              </p>
            </div>
            <div class="relative ml-4 flex-none">
              <input
                type="checkbox"
                class="sr-only"
                :checked="account.auto_funding_enabled"
                @change="toggleAutoFunding"
              />
              <div
                class="h-6 w-10 rounded-full transition-colors"
                :class="account.auto_funding_enabled ? 'bg-ocean-400' : 'bg-neutral-300'"
              />
              <div
                class="absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform"
                :class="account.auto_funding_enabled ? 'translate-x-4' : 'translate-x-0.5'"
              />
            </div>
          </label>

          <button
            type="button"
            :disabled="funding"
            class="w-full rounded-subcard bg-ocean-400 py-2.5 text-sm font-medium text-white hover:bg-ocean-600 disabled:opacity-50"
            @click="triggerFunding"
          >
            {{ funding ? "Running…" : "Run funding now" }}
          </button>

          <!-- Result -->
          <div
            v-if="fundingResult"
            class="rounded-subcard border px-3 py-2.5 text-sm"
            :class="
              nothingDue
                ? 'border-neutral-200 bg-neutral-50 text-neutral-600'
                : 'border-mint-200 bg-mint-50 text-mint-700'
            "
          >
            <template v-if="nothingDue">
              Nothing currently due.
              <span v-if="fundingNextDate" class="text-neutral-500">
                Next funding event: {{ fundingNextDate }}.
              </span>
            </template>
            <template v-else>
              {{ fundingResult.transfers }} transfer{{ fundingResult.transfers === 1 ? "" : "s" }}
              completed.
            </template>
            <ul
              v-if="fundingResult.warnings.length"
              class="mt-1.5 space-y-0.5 text-xs text-amber-600"
            >
              <li v-for="w in fundingResult.warnings" :key="w">{{ w }}</li>
            </ul>
            <div v-if="fundingResult.skipped_budgets.length" class="mt-1.5">
              <span class="text-xs font-medium">Skipped (paused):</span>
              <ul class="mt-0.5 space-y-0.5 text-xs opacity-80">
                <li v-for="name in fundingResult.skipped_budgets" :key="name">{{ name }}</li>
              </ul>
            </div>
          </div>
          <div
            v-if="fundingError"
            class="rounded-subcard border border-coral-200 bg-coral-50 px-3 py-2.5 text-sm text-coral-600"
          >
            {{ fundingError }}
          </div>
        </div>
      </section>

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
      </section>
    </div>

    <!-- Invite confirmation sheet — step 2 of the invite flow.
         Echoes the email back to the user before committing the send,
         satisfying the UX requirement that the address be confirmed
         before the invitation is created.  Cancelling here returns the
         user to the email-entry form (inviteOpen stays true) so they
         can correct a typo without starting over. -->
    <ConfirmSheet
      :open="inviteConfirm"
      title="Send co-owner invitation?"
      :message="`Send a co-owner invitation to ${inviteEmail}? They will receive an email with a link to accept or decline.`"
      confirm-label="Send invitation"
      tone="ocean"
      @confirm="doSendInvite"
      @cancel="inviteConfirm = false"
    />

    <!-- Delete confirmation sheet -->
    <ConfirmSheet
      :open="confirmDelete"
      title="Delete account?"
      :message="`This will permanently delete &quot;${account?.name}&quot; and all its budgets, transactions, and allocations. This cannot be undone.`"
      confirm-label="Delete account"
      @confirm="deleteAccount"
      @cancel="confirmDelete = false"
    />
  </AppShell>
</template>
