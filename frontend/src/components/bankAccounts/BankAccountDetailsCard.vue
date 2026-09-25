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
            {{ account.accountNumber ? `····${account.accountNumber.slice(-4)}` : "—" }}
          </span>
          <button
            type="button"
            class="flex h-6 w-6 flex-none items-center justify-center rounded-full text-neutral-400 hover:bg-neutral-100 hover:text-neutral-600"
            aria-label="Edit account number"
            @click="emit('edit')"
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
</template>
