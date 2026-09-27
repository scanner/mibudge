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
    class="rounded-card border border-accent-border bg-surface px-4 py-4"
  >
    <label class="mb-1.5 block text-label text-fg" for="edit-name">
      Account name
    </label>
    <input
      id="edit-name"
      v-model="name"
      type="text"
      class="w-full rounded-control border border-border-strong px-3 py-2.5 text-input text-fg focus:border-border-focus focus:outline-none focus:ring-1 focus:ring-border-focus"
      @keydown.enter="emit('save')"
      @keydown.escape="emit('cancel')"
    />
    <label
      class="mb-1.5 mt-3 block text-label text-fg"
      for="edit-account-number"
    >
      Account number
    </label>
    <input
      id="edit-account-number"
      v-model="accountNumber"
      type="text"
      inputmode="numeric"
      class="w-full rounded-control border border-border-strong px-3 py-2.5 font-mono text-input text-fg focus:border-border-focus focus:outline-none focus:ring-1 focus:ring-border-focus"
      @keydown.enter="emit('save')"
      @keydown.escape="emit('cancel')"
    />
    <p v-if="nameError" class="mt-1 text-meta text-danger-fg">
      {{ nameError }}
    </p>
    <div class="mt-3 flex gap-2">
      <button
        type="button"
        :disabled="saving"
        class="flex-1 rounded-control bg-accent py-2 text-label text-fg-on-accent hover:bg-accent-hover disabled:opacity-50"
        @click="emit('save')"
      >
        {{ saving ? "Saving…" : "Save" }}
      </button>
      <button
        type="button"
        class="flex-1 rounded-control border border-border py-2 text-label text-fg hover:bg-surface-sunken"
        @click="emit('cancel')"
      >
        Cancel
      </button>
    </div>
  </div>

  <!-- Account name heading (non-editing) -->
  <div v-else>
    <div class="flex items-center gap-2">
      <h1 class="text-page-title text-fg">
        {{ account.name }}
      </h1>
      <button
        type="button"
        class="flex h-7 w-7 flex-none items-center justify-center rounded-pill text-fg-muted hover:bg-surface-muted hover:text-fg-muted"
        aria-label="Edit account"
        @click="emit('edit')"
      >
        <IconPencil class="size-icon-sm" />
      </button>
    </div>
    <p class="text-body-sm text-fg-muted">
      {{ accountTypeLabel(account.accountType) }}
      <template v-if="bankName"> · {{ bankName }}</template>
    </p>
  </div>
</template>
