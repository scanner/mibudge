<script setup lang="ts">
//
// AccountView — user profile hub + bank accounts list + settings.
// Route shell over `useAccountHub`.
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
import EmptyState from "@/components/base/EmptyState.vue";
import MoneyAmount from "@/components/base/MoneyAmount.vue";
import { accountTypeMeta } from "@/domain/labels";
import { useSignOut } from "@/features/auth/useSignOut";
import { useAccountHub } from "@/features/settings/useAccountHub";
import AppShell from "@/features/shell/AppShell.vue";
import { useAccountContextStore } from "@/stores/accountContext";
import { useSessionStore } from "@/stores/session";
import BaseSelect from "@/components/base/BaseSelect.vue";
import BaseSectionHeader from "@/components/base/BaseSectionHeader.vue";
import BaseCard from "@/components/base/BaseCard.vue";
import BaseListRow from "@/components/base/BaseListRow.vue";

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
        <BaseCard
          as="button"
          padded
          class="flex w-full items-center gap-4 text-left hover:bg-surface-sunken"
          type="button"
          @click="router.push({ name: 'user-profile' })"
        >
          <div
            class="flex h-12 w-12 flex-none items-center justify-center rounded-pill bg-accent-subtle text-title text-accent-fg"
            aria-hidden="true"
          >
            <template v-if="initials">{{ initials }}</template>
            <IconUser v-else class="size-icon-lg" />
          </div>
          <div class="min-w-0 flex-1">
            <div class="truncate text-item-title text-fg">
              {{ auth.user?.name || auth.user?.username || "—" }}
            </div>
            <div class="text-meta text-fg-muted">{{ auth.user?.username }}</div>
          </div>
          <IconChevronRight class="size-icon-md flex-none text-icon-muted" />
        </BaseCard>
      </section>

      <!--
        Section 2 — Bank accounts list
      -->
      <section>
        <BaseSectionHeader title="Bank accounts" class="mb-2 px-1" />
        <BaseCard>
          <ul>
            <li
              v-for="(account, idx) in ctx.accounts"
              :key="account.id"
              :class="idx > 0 ? 'border-t border-border-subtle' : ''"
            >
              <BaseListRow
                as="button"
                @click="
                  router.push({
                    name: 'bank-account-detail',
                    params: { id: account.id },
                  })
                "
              >
                <span
                  class="mt-0.5 h-2.5 w-2.5 flex-none rounded-pill bg-accent"
                />
                <div class="min-w-0 flex-1">
                  <div class="truncate text-item-title text-fg">
                    {{ account.name }}
                  </div>
                  <div class="text-meta text-fg-muted">
                    {{
                      accountTypeMeta(
                        account.accountType,
                        account.accountNumber,
                      )
                    }}
                  </div>
                </div>
                <div class="flex flex-none flex-col items-end gap-0.5">
                  <span class="text-meta text-fg-muted">
                    Available:
                    <MoneyAmount :amount="account.availableBalance" size="sm" />
                  </span>
                  <span class="text-meta text-fg-muted">
                    Posted:
                    <MoneyAmount :amount="account.postedBalance" size="sm" />
                  </span>
                  <span
                    v-if="unallocatedFor(account)"
                    class="text-meta font-medium text-money-positive"
                  >
                    <MoneyAmount
                      :amount="unallocatedFor(account)!.balance"
                      size="sm"
                    />
                    unallocated
                  </span>
                  <span
                    v-if="nextFundingFor(account)"
                    class="text-meta text-accent-fg"
                  >
                    <MoneyAmount :amount="nextFundingFor(account)!" size="sm" />
                    next event
                  </span>
                </div>
                <IconChevronRight
                  class="size-icon-sm flex-none text-icon-muted"
                />
              </BaseListRow>
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
              class="flex w-full items-center gap-3 rounded-b-card px-4 py-3.5 text-left text-label text-fg-link hover:bg-accent-subtle"
              @click="router.push({ name: 'bank-account-create' })"
            >
              <span
                class="flex h-6 w-6 items-center justify-center rounded-pill border border-dashed border-accent-border"
              >
                <IconPlus class="size-icon-xs" />
              </span>
              Add bank account
            </button>
          </div>
        </BaseCard>

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
        <BaseSectionHeader title="Settings" class="mb-2 px-1" />
        <BaseCard>
          <!-- Default account -->
          <BaseListRow class="justify-between">
            <div class="flex items-center gap-3 text-fg">
              <IconBuildingBank class="size-icon-sm" />
              <span class="text-body-sm">Default account</span>
            </div>
            <BaseSelect
              :model-value="defaultAccountId"
              :disabled="ctx.accounts.length === 0"
              @update:model-value="setDefaultAccount(String($event ?? ''))"
              size="sm"
              inline
            >
              <option value="">None</option>
              <option v-for="a in ctx.accounts" :key="a.id" :value="a.id">
                {{ a.name }}
              </option>
            </BaseSelect>
          </BaseListRow>
          <p
            v-if="defaultAccountError"
            class="px-4 pb-3 text-meta text-danger-fg"
            role="alert"
          >
            {{ defaultAccountError }}
          </p>

          <!-- Security & notifications -->
          <div class="border-t border-border-subtle">
            <BaseListRow
              as="button"
              @click="router.push({ name: 'account-settings' })"
            >
              <IconLock class="size-icon-sm text-fg-muted" />
              <span class="flex-1 text-body-sm text-fg"
                >Security &amp; Notifications</span
              >
              <IconChevronRight
                class="size-icon-sm flex-none text-icon-muted"
              />
            </BaseListRow>
          </div>

          <!-- Sign out -->
          <div class="border-t border-border-subtle">
            <button
              type="button"
              class="flex w-full items-center gap-3 rounded-b-card px-4 py-3.5 text-left text-label text-danger-fg hover:bg-danger-bg"
              @click="signOut"
            >
              Sign out
            </button>
          </div>
        </BaseCard>
      </section>
    </div>
  </AppShell>
</template>
