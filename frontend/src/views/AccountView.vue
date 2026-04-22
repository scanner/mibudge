<script setup lang="ts">
//
// AccountView — user profile hub + bank accounts list + settings.
// (UI_SPEC §4.7)
//
// Three sections:
//   1. Profile card — avatar initials, name, username → /account/profile/
//   2. Bank accounts — one row per account with balance + unallocated
//   3. Settings — sign out (default account is GAP-1, placeholder only)
//

// 3rd party imports
//
import { IconBuildingBank, IconChevronRight, IconPlus, IconUser } from "@tabler/icons-vue";
import { computed, onMounted } from "vue";
import { useRouter } from "vue-router";

// app imports
//
import EmptyState from "@/components/shared/EmptyState.vue";
import MoneyAmount from "@/components/shared/MoneyAmount.vue";
import AppShell from "@/components/layout/AppShell.vue";
import { useAccountContextStore } from "@/stores/accountContext";
import { useAuthStore } from "@/stores/auth";
import { useBudgetsStore } from "@/stores/budgets";

////////////////////////////////////////////////////////////////////////
//
const router = useRouter();
const auth = useAuthStore();
const ctx = useAccountContextStore();
const budgets = useBudgetsStore();

////////////////////////////////////////////////////////////////////////
//
// Avatar initials from the user's name or username.
//
const initials = computed(() => {
  const name = auth.user?.name || auth.user?.username || "";
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0].toUpperCase())
    .join("");
});

////////////////////////////////////////////////////////////////////////
//
// Account-type display labels.
//
const ACCOUNT_TYPE_LABELS: Record<string, string> = {
  C: "Checking",
  S: "Savings",
  X: "Credit card",
};

function accountTypeMeta(account: (typeof ctx.accounts)[0]): string {
  const type = ACCOUNT_TYPE_LABELS[account.account_type] ?? account.account_type;
  if (account.account_number) {
    return `${type} ····${account.account_number.slice(-4)}`;
  }
  return type;
}

////////////////////////////////////////////////////////////////////////
//
// Unallocated budget for a given account (loaded lazily from budgets store).
//
function unallocatedFor(account: (typeof ctx.accounts)[0]) {
  return account.unallocated_budget ? budgets.byId(account.unallocated_budget) : null;
}

onMounted(() => {
  // Ensure accounts list is fresh.
  ctx.refresh();
  // Load unallocated budget for each account so we can show "$X free".
  for (const account of ctx.accounts) {
    if (account.unallocated_budget && !budgets.byId(account.unallocated_budget)) {
      budgets.fetchOne(account.unallocated_budget);
    }
  }
});

////////////////////////////////////////////////////////////////////////
//
async function signOut() {
  auth.clear();
  ctx.clear();
  router.push("/login/");
}
</script>

<template>
  <AppShell>
    <div class="mx-auto max-w-lg space-y-5 py-4">
      <!--
        Section 1 — Profile card
      -->
      <section>
        <button
          type="button"
          class="flex w-full items-center gap-4 rounded-card border border-neutral-200 bg-white px-4 py-4 text-left hover:bg-neutral-50"
          @click="router.push('/account/profile/')"
        >
          <div
            class="flex h-12 w-12 flex-none items-center justify-center rounded-full bg-ocean-50 text-[18px] font-medium text-ocean-600"
            aria-hidden="true"
          >
            <template v-if="initials">{{ initials }}</template>
            <IconUser v-else class="h-6 w-6" />
          </div>
          <div class="min-w-0 flex-1">
            <div class="truncate text-[15px] font-medium text-neutral-900">
              {{ auth.user?.name || auth.user?.username || "—" }}
            </div>
            <div class="text-xs text-neutral-500">{{ auth.user?.username }}</div>
          </div>
          <IconChevronRight class="h-5 w-5 flex-none text-neutral-400" />
        </button>
      </section>

      <!--
        Section 2 — Bank accounts list
      -->
      <section>
        <h2 class="mb-2 px-1 text-[11px] font-semibold uppercase tracking-wider text-neutral-500">
          Bank accounts
        </h2>
        <div class="overflow-hidden rounded-card border border-neutral-200 bg-white">
          <ul>
            <li
              v-for="(account, idx) in ctx.accounts"
              :key="account.id"
              :class="idx > 0 ? 'border-t border-neutral-100' : ''"
            >
              <button
                type="button"
                class="flex w-full items-center gap-3 px-4 py-3.5 text-left hover:bg-neutral-50"
                @click="router.push(`/account/bank-accounts/${account.id}/`)"
              >
                <span class="mt-0.5 h-2.5 w-2.5 flex-none rounded-full bg-ocean-400" />
                <div class="min-w-0 flex-1">
                  <div class="truncate text-[15px] font-medium text-neutral-900">
                    {{ account.name }}
                  </div>
                  <div class="text-xs text-neutral-500">{{ accountTypeMeta(account) }}</div>
                </div>
                <div class="flex flex-none flex-col items-end gap-0.5">
                  <MoneyAmount
                    :amount="account.posted_balance"
                    :currency="account.posted_balance_currency"
                    size="sm"
                  />
                  <span
                    v-if="unallocatedFor(account)"
                    class="text-[11px] font-medium text-mint-600"
                  >
                    <MoneyAmount
                      :amount="unallocatedFor(account)!.balance"
                      :currency="unallocatedFor(account)!.balance_currency"
                      size="sm"
                    />
                    free
                  </span>
                </div>
                <IconChevronRight class="h-4 w-4 flex-none text-neutral-400" />
              </button>
            </li>
          </ul>

          <!-- Add bank account row -->
          <div :class="ctx.accounts.length > 0 ? 'border-t border-neutral-100' : ''">
            <button
              type="button"
              class="flex w-full items-center gap-3 rounded-b-card px-4 py-3.5 text-left text-sm font-medium text-ocean-600 hover:bg-ocean-50"
              @click="router.push('/account/bank-accounts/create/')"
            >
              <span
                class="flex h-6 w-6 items-center justify-center rounded-full border border-dashed border-ocean-400"
              >
                <IconPlus class="h-3.5 w-3.5" />
              </span>
              Add bank account
            </button>
          </div>
        </div>

        <EmptyState
          v-if="ctx.accounts.length === 0 && !ctx.loading"
          title="No bank accounts yet"
          action-label="Add your first account"
          @action="router.push('/account/bank-accounts/create/')"
        />
      </section>

      <!--
        Section 3 — Settings
      -->
      <section>
        <h2 class="mb-2 px-1 text-[11px] font-semibold uppercase tracking-wider text-neutral-500">
          Settings
        </h2>
        <div class="overflow-hidden rounded-card border border-neutral-200 bg-white">
          <!-- Default account — GAP-1: placeholder until User.default_bank_account exists -->
          <div class="flex items-center justify-between px-4 py-3.5 text-neutral-400">
            <div class="flex items-center gap-3">
              <IconBuildingBank class="h-4 w-4" />
              <span class="text-sm">Default account</span>
            </div>
            <!-- TODO: GAP-1 — not implemented until User.default_bank_account field is added -->
            <span class="text-xs text-neutral-400">Coming soon</span>
          </div>

          <!-- Sign out -->
          <div class="border-t border-neutral-100">
            <button
              type="button"
              class="flex w-full items-center gap-3 rounded-b-card px-4 py-3.5 text-left text-sm font-medium text-coral-600 hover:bg-coral-50"
              @click="signOut"
            >
              Sign out
            </button>
          </div>
        </div>
      </section>
    </div>
  </AppShell>
</template>
