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
import BaseIconButton from "@/components/base/BaseIconButton.vue";
import BaseSectionHeader from "@/components/base/BaseSectionHeader.vue";
import BaseCard from "@/components/base/BaseCard.vue";
import BaseListRow from "@/components/base/BaseListRow.vue";

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
  <BaseCard as="section">
    <BaseSectionHeader title="Details" card />
    <dl>
      <BaseListRow class="justify-between">
        <dt class="text-body-sm text-fg-muted">Account number</dt>
        <dd class="flex items-center gap-2">
          <span class="font-mono text-amount-sm text-fg">
            {{
              account.accountNumber
                ? `····${account.accountNumber.slice(-4)}`
                : "—"
            }}
          </span>
          <BaseIconButton
            label="Edit account number"
            size="sm"
            @click="emit('edit')"
          >
            <IconPencil class="size-icon-xs" />
          </BaseIconButton>
        </dd>
      </BaseListRow>
      <BaseListRow class="justify-between">
        <dt class="text-body-sm text-fg-muted">Bank</dt>
        <dd class="text-body-sm text-fg">{{ bankName ?? "—" }}</dd>
      </BaseListRow>
      <BaseListRow class="justify-between">
        <dt class="text-body-sm text-fg-muted">Created</dt>
        <dd class="text-body-sm text-fg">{{ createdDate }}</dd>
      </BaseListRow>
    </dl>
  </BaseCard>
</template>
