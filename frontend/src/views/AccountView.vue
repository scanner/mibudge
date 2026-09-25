<script setup lang="ts">
//
// AccountView — user profile hub + bank accounts list + settings.
// (UI_SPEC §4.7)  Route shell over `useAccountHub`.
//
// Three sections:
//   1. Profile card — avatar initials, name, username → profile page
//   2. Bank accounts — one row per account with balances + unallocated
//   3. Settings — default account picker, security link, sign out
//

// 3rd party imports
//
import {
  IconBuildingBank,
  IconChevronRight,
  IconLock,
  IconPlus,
  IconUser,
} from "@tabler/icons-vue";
import { useRouter } from "vue-router";

// app imports
//
import EmptyState from "@/components/shared/EmptyState.vue";
import MoneyAmount from "@/components/shared/MoneyAmount.vue";
import { accountTypeMeta } from "@/domain/labels";
import { useSignOut } from "@/features/auth/useSignOut";
import { useAccountHub } from "@/features/settings/useAccountHub";
import AppShell from "@/features/shell/AppShell.vue";
import { useAccountContextStore } from "@/stores/accountContext";
import { useSessionStore } from "@/stores/session";

////////////////////////////////////////////////////////////////////////
//
const router = useRouter();
const auth = useSessionStore();
const ctx = useAccountContextStore();
const {
  initials,
  unallocatedFor,
  nextFundingFor,
  settingDefault,
  defaultAccountError,
  setDefaultAccount,
} = useAccountHub();
const { signOut } = useSignOut();
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
          @click="router.push({ name: 'user-profile' })"
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
            <div class="text-xs text-secondary">{{ auth.user?.username }}</div>
          </div>
          <IconChevronRight class="h-5 w-5 flex-none text-neutral-400" />
        </button>
      </section>

      <!--
        Section 2 — Bank accounts list
      -->
      <section>
        <h2
          class="mb-2 px-1 text-[11px] font-semibold uppercase tracking-wider text-secondary"
        >
          Bank accounts
        </h2>
        <div
          class="overflow-hidden rounded-card border border-neutral-200 bg-white"
        >
          <ul>
            <li
              v-for="(account, idx) in ctx.accounts"
              :key="account.id"
              :class="idx > 0 ? 'border-t border-neutral-100' : ''"
            >
              <button
                type="button"
                class="flex w-full items-center gap-3 px-4 py-3.5 text-left hover:bg-neutral-50"
                @click="
                  router.push({
                    name: 'bank-account-detail',
                    params: { id: account.id },
                  })
                "
              >
                <span
                  class="mt-0.5 h-2.5 w-2.5 flex-none rounded-full bg-ocean-400"
                />
                <div class="min-w-0 flex-1">
                  <div
                    class="truncate text-[15px] font-medium text-neutral-900"
                  >
                    {{ account.name }}
                  </div>
                  <div class="text-xs text-secondary">
                    {{
                      accountTypeMeta(
                        account.accountType,
                        account.accountNumber,
                      )
                    }}
                  </div>
                </div>
                <div class="flex flex-none flex-col items-end gap-0.5">
                  <span class="text-[11px] text-secondary">
                    Available:
                    <MoneyAmount :amount="account.availableBalance" size="sm" />
                  </span>
                  <span class="text-[11px] text-secondary">
                    Posted:
                    <MoneyAmount :amount="account.postedBalance" size="sm" />
                  </span>
                  <span
                    v-if="unallocatedFor(account)"
                    class="text-[11px] font-medium text-mint-600"
                  >
                    <MoneyAmount
                      :amount="unallocatedFor(account)!.balance"
                      size="sm"
                    />
                    unallocated
                  </span>
                  <span
                    v-if="nextFundingFor(account)"
                    class="text-[11px] text-ocean-500"
                  >
                    <MoneyAmount :amount="nextFundingFor(account)!" size="sm" />
                    next event
                  </span>
                </div>
                <IconChevronRight class="h-4 w-4 flex-none text-neutral-400" />
              </button>
            </li>
          </ul>

          <!-- Add bank account row -->
          <div
            :class="
              ctx.accounts.length > 0 ? 'border-t border-neutral-100' : ''
            "
          >
            <button
              type="button"
              class="flex w-full items-center gap-3 rounded-b-card px-4 py-3.5 text-left text-sm font-medium text-ocean-600 hover:bg-ocean-50"
              @click="router.push({ name: 'bank-account-create' })"
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
          @action="router.push({ name: 'bank-account-create' })"
        />
      </section>

      <!--
        Section 3 — Settings
      -->
      <section>
        <h2
          class="mb-2 px-1 text-[11px] font-semibold uppercase tracking-wider text-secondary"
        >
          Settings
        </h2>
        <div
          class="overflow-hidden rounded-card border border-neutral-200 bg-white"
        >
          <!-- Default account -->
          <div class="flex items-center justify-between px-4 py-3.5">
            <div class="flex items-center gap-3 text-neutral-700">
              <IconBuildingBank class="h-4 w-4" />
              <span class="text-sm">Default account</span>
            </div>
            <select
              :value="auth.user?.defaultBankAccountId ?? ''"
              :disabled="settingDefault || ctx.accounts.length === 0"
              class="rounded-md border border-neutral-200 bg-white py-1 pl-2 pr-6 text-xs text-neutral-700 focus:border-ocean-400 focus:outline-none focus:ring-1 focus:ring-ocean-400 disabled:opacity-50"
              @change="
                setDefaultAccount(($event.target as HTMLSelectElement).value)
              "
            >
              <option value="">None</option>
              <option v-for="a in ctx.accounts" :key="a.id" :value="a.id">
                {{ a.name }}
              </option>
            </select>
          </div>
          <p
            v-if="defaultAccountError"
            class="px-4 pb-3 text-xs text-coral-600"
            role="alert"
          >
            {{ defaultAccountError }}
          </p>

          <!-- Security & notifications -->
          <div class="border-t border-neutral-100">
            <button
              type="button"
              class="flex w-full items-center gap-3 px-4 py-3.5 text-left hover:bg-neutral-50"
              @click="router.push({ name: 'account-settings' })"
            >
              <IconLock class="h-4 w-4 text-neutral-700" />
              <span class="flex-1 text-sm text-neutral-700"
                >Security &amp; Notifications</span
              >
              <IconChevronRight class="h-4 w-4 flex-none text-neutral-400" />
            </button>
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
