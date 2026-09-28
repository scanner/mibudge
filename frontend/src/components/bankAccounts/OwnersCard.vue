<script setup lang="ts">
//
// OwnersCard — the account's owners and the inline "invite co-owner"
// email form.  Presentational: the email is a `v-model`; emits `open`,
// `review` (validate and ask to confirm) and `close`.
//

// app imports
//
import BaseButton from "@/components/base/BaseButton.vue";
import BaseFormField from "@/components/base/BaseFormField.vue";
import BaseInput from "@/components/base/BaseInput.vue";
import BaseSectionHeader from "@/components/base/BaseSectionHeader.vue";
import BaseCard from "@/components/base/BaseCard.vue";
import BaseListRow from "@/components/base/BaseListRow.vue";

////////////////////////////////////////////////////////////////////////
//
defineProps<{
  owners: string[];
  formOpen: boolean;
  sending: boolean;
  sent: boolean;
  error: string | null;
}>();

const email = defineModel<string>("email", { required: true });

const emit = defineEmits<{
  (e: "open"): void;
  (e: "review"): void;
  (e: "close"): void;
}>();
</script>

<template>
  <!-- Owners + invite form
       The invite form lives inside this section so it visually belongs
       with the owners list.  The two-step flow (enter email → confirm
       in ConfirmSheet) keeps the destructive-action confirmation
       pattern consistent with the delete flow below. -->
  <BaseCard as="section">
    <div
      class="flex items-center justify-between border-b border-border-subtle px-4 py-3"
    >
      <BaseSectionHeader title="Owners" />
      <BaseButton
        v-if="!formOpen"
        variant="link"
        size="sm"
        @click="emit('open')"
      >
        + Invite co-owner
      </BaseButton>
    </div>

    <!-- Current owners list -->
    <ul>
      <BaseListRow
        v-for="owner in owners"
        as="li"
        class="text-body-sm text-fg"
        :key="owner"
      >
        {{ owner }}
      </BaseListRow>
      <BaseListRow
        v-if="!owners.length"
        as="li"
        class="text-body-sm text-fg-subtle"
      >
        —
      </BaseListRow>
    </ul>

    <!-- Inline invite form — step 1: enter the email address.
         Appears below the owner list when inviteOpen is true.
         The "Review" button triggers client-side validation and then
         opens the ConfirmSheet for step 2 rather than sending directly,
         giving the user a chance to double-check the address. -->
    <div v-if="formOpen" class="border-t border-border-subtle px-4 py-4">
      <BaseFormField id="invite-email" label="Email address to invite">
        <template #default="{ id, describedBy, invalid }">
          <BaseInput
            :id="id"
            v-model="email"
            type="email"
            autocomplete="email"
            placeholder="colleague@example.com"
            @keydown.enter="emit('review')"
            @keydown.escape="emit('close')"
            :aria-describedby="describedBy"
            :invalid="invalid"
          />
        </template>
      </BaseFormField>
      <p v-if="error" class="mt-1 text-meta text-danger-fg">{{ error }}</p>
      <div class="mt-3 flex gap-2">
        <BaseButton :loading="sending" class="flex-1" @click="emit('review')">
          {{ sending ? "Sending…" : "Review" }}
        </BaseButton>
        <BaseButton variant="secondary" class="flex-1" @click="emit('close')">
          Cancel
        </BaseButton>
      </div>
    </div>

    <!-- Success banner shown after a successful invite send.
         Displayed inside the Owners card so it is contextually near
         the action that triggered it. -->
    <div
      v-if="sent && !formOpen"
      class="border-t border-border-subtle px-4 py-3 text-body-sm text-success-fg"
    >
      Invitation sent.
    </div>
  </BaseCard>
</template>
