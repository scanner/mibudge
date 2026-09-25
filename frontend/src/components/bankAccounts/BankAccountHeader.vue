<script setup lang="ts">
//
// BankAccountHeader — the account name with its type and bank, or the
// inline editor for name and account number.  Presentational: the
// fields are `v-model`s; emits `edit`, `save` and `cancel`.
//

// 3rd party imports
//
import { IconPencil } from "@tabler/icons-vue";

// app imports
//
import { accountTypeLabel } from "@/domain/labels";
import type { BankAccount } from "@/models/bankAccount";

////////////////////////////////////////////////////////////////////////
//
defineProps<{
  account: BankAccount;
  bankName: string | null;
  editing: boolean;
  saving: boolean;
  nameError: string | null;
}>();

const name = defineModel<string>("name", { required: true });
const accountNumber = defineModel<string>("accountNumber", { required: true });

const emit = defineEmits<{
  (e: "edit"): void;
  (e: "save"): void;
  (e: "cancel"): void;
}>();
</script>

<template>
  <!-- Inline name editor -->
  <div
    v-if="editing"
    class="rounded-card border border-ocean-400 bg-white px-4 py-4"
  >
    <label
      class="mb-1.5 block text-sm font-medium text-neutral-700"
      for="edit-name"
    >
      Account name
    </label>
    <input
      id="edit-name"
      v-model="name"
      type="text"
      class="w-full rounded-subcard border border-neutral-200 px-3 py-2.5 text-sm text-neutral-900 focus:border-ocean-400 focus:outline-none focus:ring-1 focus:ring-ocean-400"
      @keydown.enter="emit('save')"
      @keydown.escape="emit('cancel')"
    />
    <label
      class="mb-1.5 mt-3 block text-sm font-medium text-neutral-700"
      for="edit-account-number"
    >
      Account number
    </label>
    <input
      id="edit-account-number"
      v-model="accountNumber"
      type="text"
      inputmode="numeric"
      class="w-full rounded-subcard border border-neutral-200 px-3 py-2.5 font-mono text-sm text-neutral-900 focus:border-ocean-400 focus:outline-none focus:ring-1 focus:ring-ocean-400"
      @keydown.enter="emit('save')"
      @keydown.escape="emit('cancel')"
    />
    <p v-if="nameError" class="mt-1 text-xs text-coral-600">{{ nameError }}</p>
    <div class="mt-3 flex gap-2">
      <button
        type="button"
        :disabled="saving"
        class="flex-1 rounded-subcard bg-ocean-400 py-2 text-sm font-medium text-white hover:bg-ocean-600 disabled:opacity-50"
        @click="emit('save')"
      >
        {{ saving ? "Saving…" : "Save" }}
      </button>
      <button
        type="button"
        class="flex-1 rounded-subcard border border-neutral-200 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-50"
        @click="emit('cancel')"
      >
        Cancel
      </button>
    </div>
  </div>

  <!-- Account name heading (non-editing) -->
  <div v-else>
    <div class="flex items-center gap-2">
      <h1 class="text-[22px] font-medium text-neutral-900">
        {{ account.name }}
      </h1>
      <button
        type="button"
        class="flex h-7 w-7 flex-none items-center justify-center rounded-full text-neutral-400 hover:bg-neutral-100 hover:text-neutral-600"
        aria-label="Edit account"
        @click="emit('edit')"
      >
        <IconPencil class="h-4 w-4" />
      </button>
    </div>
    <p class="text-sm text-secondary">
      {{ accountTypeLabel(account.accountType) }}
      <template v-if="bankName"> · {{ bankName }}</template>
    </p>
  </div>
</template>
