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
  defaultAccountId,
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
          class="flex w-full items-center gap-4 rounded-card border border-border bg-surface px-4 py-4 text-left hover:bg-surface-sunken"
          @click="router.push({ name: 'user-profile' })"
        >
          <div
            class="flex h-12 w-12 flex-none items-center justify-center rounded-full bg-accent-subtle text-[18px] font-medium text-accent-fg"
            aria-hidden="true"
          >
            <template v-if="initials">{{ initials }}</template>
            <IconUser v-else class="h-6 w-6" />
          </div>
          <div class="min-w-0 flex-1">
            <div class="truncate text-[15px] font-medium text-fg">
              {{ auth.user?.name || auth.user?.username || "—" }}
            </div>
            <div class="text-xs text-fg-muted">{{ auth.user?.username }}</div>
          </div>
          <IconChevronRight class="h-5 w-5 flex-none text-icon-muted" />
        </button>
      </section>

      <!--
        Section 2 — Bank accounts list
      -->
      <section>
        <h2
          class="mb-2 px-1 text-[11px] font-semibold uppercase tracking-wider text-fg-muted"
        >
          Bank accounts
        </h2>
        <div
          class="overflow-hidden rounded-card border border-border bg-surface"
        >
          <ul>
            <li
              v-for="(account, idx) in ctx.accounts"
              :key="account.id"
              :class="idx > 0 ? 'border-t border-border-subtle' : ''"
            >
              <button
                type="button"
                class="flex w-full items-center gap-3 px-4 py-3.5 text-left hover:bg-surface-sunken"
                @click="
                  router.push({
                    name: 'bank-account-detail',
                    params: { id: account.id },
                  })
                "
              >
                <span
                  class="mt-0.5 h-2.5 w-2.5 flex-none rounded-full bg-accent"
                />
                <div class="min-w-0 flex-1">
                  <div class="truncate text-[15px] font-medium text-fg">
                    {{ account.name }}
                  </div>
                  <div class="text-xs text-fg-muted">
                    {{
                      accountTypeMeta(
                        account.accountType,
                        account.accountNumber,
                      )
                    }}
                  </div>
                </div>
                <div class="flex flex-none flex-col items-end gap-0.5">
                  <span class="text-[11px] text-fg-muted">
                    Available:
                    <MoneyAmount :amount="account.availableBalance" size="sm" />
                  </span>
                  <span class="text-[11px] text-fg-muted">
                    Posted:
                    <MoneyAmount :amount="account.postedBalance" size="sm" />
                  </span>
                  <span
                    v-if="unallocatedFor(account)"
                    class="text-[11px] font-medium text-money-positive"
                  >
                    <MoneyAmount
                      :amount="unallocatedFor(account)!.balance"
                      size="sm"
                    />
                    unallocated
                  </span>
                  <span
                    v-if="nextFundingFor(account)"
                    class="text-[11px] text-accent-fg"
                  >
                    <MoneyAmount :amount="nextFundingFor(account)!" size="sm" />
                    next event
                  </span>
                </div>
                <IconChevronRight class="h-4 w-4 flex-none text-icon-muted" />
              </button>
            </li>
          </ul>

          <!-- Add bank account row -->
          <div
            :class="
              ctx.accounts.length > 0 ? 'border-t border-border-subtle' : ''
            "
          >
            <button
              type="button"
              class="flex w-full items-center gap-3 rounded-b-card px-4 py-3.5 text-left text-sm font-medium text-fg-link hover:bg-accent-subtle"
              @click="router.push({ name: 'bank-account-create' })"
            >
              <span
                class="flex h-6 w-6 items-center justify-center rounded-full border border-dashed border-accent-border"
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
          class="mb-2 px-1 text-[11px] font-semibold uppercase tracking-wider text-fg-muted"
        >
          Settings
        </h2>
        <div
          class="overflow-hidden rounded-card border border-border bg-surface"
        >
          <!-- Default account -->
          <div class="flex items-center justify-between px-4 py-3.5">
            <div class="flex items-center gap-3 text-fg">
              <IconBuildingBank class="h-4 w-4" />
              <span class="text-sm">Default account</span>
            </div>
            <select
              :value="defaultAccountId"
              :disabled="ctx.accounts.length === 0"
              class="rounded-md border border-border-strong bg-surface py-1 pl-2 pr-6 text-xs text-fg focus:border-border-focus focus:outline-none focus:ring-1 focus:ring-border-focus disabled:opacity-50"
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
            class="px-4 pb-3 text-xs text-danger-fg"
            role="alert"
          >
            {{ defaultAccountError }}
          </p>

          <!-- Security & notifications -->
          <div class="border-t border-border-subtle">
            <button
              type="button"
              class="flex w-full items-center gap-3 px-4 py-3.5 text-left hover:bg-surface-sunken"
              @click="router.push({ name: 'account-settings' })"
            >
              <IconLock class="h-4 w-4 text-fg-muted" />
              <span class="flex-1 text-sm text-fg"
                >Security &amp; Notifications</span
              >
              <IconChevronRight class="h-4 w-4 flex-none text-icon-muted" />
            </button>
          </div>

          <!-- Sign out -->
          <div class="border-t border-border-subtle">
            <button
              type="button"
              class="flex w-full items-center gap-3 rounded-b-card px-4 py-3.5 text-left text-sm font-medium text-danger-fg hover:bg-danger-bg"
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
