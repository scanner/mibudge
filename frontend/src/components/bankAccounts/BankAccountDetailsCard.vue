<script setup lang="ts">
//
// BankAccountDetailsCard — account number, bank and creation date.
// Presentational; the pencil emits `edit`.
//

// 3rd party imports
//
import { IconPencil } from "@tabler/icons-vue";

// app imports
//
import type { BankAccount } from "@/models/bankAccount";

////////////////////////////////////////////////////////////////////////
//
defineProps<{
  account: BankAccount;
  bankName: string | null;
  createdDate: string;
}>();

const emit = defineEmits<{ (e: "edit"): void }>();
</script>

<template>
  <!-- Details -->
  <section class="overflow-hidden rounded-card border border-border bg-surface">
    <h2
      class="border-b border-border-subtle px-4 py-3 text-[11px] font-semibold uppercase tracking-wider text-fg-muted"
    >
      Details
    </h2>
    <dl class="divide-y divide-border-subtle">
      <div class="flex items-center justify-between px-4 py-3">
        <dt class="text-sm text-fg-muted">Account number</dt>
        <dd class="flex items-center gap-2">
          <span class="font-mono text-sm text-fg">
            {{
              account.accountNumber
                ? `····${account.accountNumber.slice(-4)}`
                : "—"
            }}
          </span>
          <button
            type="button"
            class="flex h-6 w-6 flex-none items-center justify-center rounded-full text-fg-muted hover:bg-surface-muted hover:text-fg-muted"
            aria-label="Edit account number"
            @click="emit('edit')"
          >
            <IconPencil class="h-3.5 w-3.5" />
          </button>
        </dd>
      </div>
      <div class="flex items-center justify-between px-4 py-3">
        <dt class="text-sm text-fg-muted">Bank</dt>
        <dd class="text-sm text-fg">{{ bankName ?? "—" }}</dd>
      </div>
      <div class="flex items-center justify-between px-4 py-3">
        <dt class="text-sm text-fg-muted">Created</dt>
        <dd class="text-sm text-fg">{{ createdDate }}</dd>
      </div>
    </dl>
  </section>
</template>
