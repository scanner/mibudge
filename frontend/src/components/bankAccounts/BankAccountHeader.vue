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
import BaseButton from "@/components/base/BaseButton.vue";
import BaseIconButton from "@/components/base/BaseIconButton.vue";
import BaseFormField from "@/components/base/BaseFormField.vue";
import BaseInput from "@/components/base/BaseInput.vue";

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
    <BaseFormField id="edit-name" label="Account name">
      <template #default="{ id, describedBy, invalid }">
        <BaseInput
          :id="id"
          v-model="name"
          type="text"
          @keydown.enter="emit('save')"
          @keydown.escape="emit('cancel')"
          :aria-describedby="describedBy"
          :invalid="invalid"
        />
      </template>
    </BaseFormField>
    <label
      class="mb-1.5 mt-3 block text-label text-fg"
      for="edit-account-number"
    >
      Account number
    </label>
    <BaseInput
      id="edit-account-number"
      v-model="accountNumber"
      type="text"
      inputmode="numeric"
      @keydown.enter="emit('save')"
      @keydown.escape="emit('cancel')"
      mono
    />
    <p v-if="nameError" class="mt-1 text-meta text-danger-fg">
      {{ nameError }}
    </p>
    <div class="mt-3 flex gap-2">
      <BaseButton :loading="saving" class="flex-1" @click="emit('save')">
        {{ saving ? "Saving…" : "Save" }}
      </BaseButton>
      <BaseButton variant="secondary" class="flex-1" @click="emit('cancel')">
        Cancel
      </BaseButton>
    </div>
  </div>

  <!-- Account name heading (non-editing) -->
  <div v-else>
    <div class="flex items-center gap-2">
      <h1 class="text-page-title text-fg">
        {{ account.name }}
      </h1>
      <BaseIconButton label="Edit account" size="sm" @click="emit('edit')">
        <IconPencil class="size-icon-sm" />
      </BaseIconButton>
    </div>
    <p class="text-body-sm text-fg-muted">
      {{ accountTypeLabel(account.accountType) }}
      <template v-if="bankName"> · {{ bankName }}</template>
    </p>
  </div>
</template>
