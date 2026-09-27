<script setup lang="ts">
//
// PasswordSection — change the account password.  Feature component
// (settings); state and submit live in `usePasswordChange`.  Accounts
// without a usable password (created by invitation) get a link to the
// set-password email flow instead of the form.
//

// 3rd party imports
//
import { useRouter } from "vue-router";

// app imports
//
import PasswordStrengthMeter from "@/components/shared/PasswordStrengthMeter.vue";
import { useSessionStore } from "@/stores/session";
import { usePasswordChange } from "./usePasswordChange";
import BaseButton from "@/components/base/BaseButton.vue";
import BaseFormField from "@/components/base/BaseFormField.vue";
import BaseInput from "@/components/base/BaseInput.vue";
import BaseSectionHeader from "@/components/base/BaseSectionHeader.vue";
import BaseCard from "@/components/base/BaseCard.vue";
import BaseBanner from "@/components/base/BaseBanner.vue";

////////////////////////////////////////////////////////////////////////
//
const router = useRouter();
const session = useSessionStore();

const {
  currentPassword,
  newPassword,
  confirmPassword,
  strengthScore,
  saving,
  success,
  submitDisabled,
  fieldError,
  formError,
  submit,
} = usePasswordChange();
</script>

<template>
  <!-- Password change card -->
  <section>
    <BaseSectionHeader title="Change password" class="mb-2 px-1" />

    <BaseCard padded>
      <!-- No usable password: guide user to reset flow -->
      <div
        v-if="!session.user?.hasUsablePassword"
        class="space-y-2 text-body-sm text-fg"
      >
        <p>
          Your account doesn't have a password set yet — this happens when your
          account was created via an invitation.
        </p>
        <BaseButton as="a" href="/accounts/password/reset/">
          Set a password via email
        </BaseButton>
      </div>

      <template v-else>
        <!-- Success banner -->
        <BaseBanner v-if="success" tone="success" class="mb-4">
          Password changed successfully.
        </BaseBanner>

        <!-- Form-level error -->
        <BaseBanner v-if="formError" tone="danger" class="mb-4">
          {{ formError }}
        </BaseBanner>

        <form class="space-y-4" @submit.prevent="submit">
          <!-- Current password -->
          <BaseFormField
            id="current-password"
            label="Current password"
            :error="fieldError('current_password')"
          >
            <template #default="{ id, describedBy, invalid }">
              <BaseInput
                :id="id"
                v-model="currentPassword"
                type="password"
                autocomplete="current-password"
                :aria-describedby="describedBy"
                :invalid="invalid"
              />
            </template>
          </BaseFormField>

          <!-- New password -->
          <BaseFormField
            id="new-password"
            label="New password"
            :error="fieldError('new_password')"
          >
            <template #default="{ id, describedBy, invalid }">
              <BaseInput
                :id="id"
                v-model="newPassword"
                type="password"
                autocomplete="new-password"
                :aria-describedby="describedBy"
                :invalid="invalid"
              />
              <PasswordStrengthMeter
                :password="newPassword"
                @score="strengthScore = $event"
              />
            </template>
          </BaseFormField>

          <!-- Confirm password -->
          <BaseFormField
            id="confirm-password"
            label="Confirm new password"
            :error="fieldError('confirm_password')"
          >
            <template #default="{ id, describedBy, invalid }">
              <BaseInput
                :id="id"
                v-model="confirmPassword"
                type="password"
                autocomplete="new-password"
                :aria-describedby="describedBy"
                :invalid="invalid"
              />
            </template>
          </BaseFormField>

          <!-- Actions -->
          <div class="flex gap-3 pt-2">
            <BaseButton type="submit" :disabled="submitDisabled" class="flex-1">
              {{ saving ? "Saving…" : "Change password" }}
            </BaseButton>
            <BaseButton
              variant="secondary"
              class="flex-1"
              @click="router.push({ name: 'account' })"
            >
              Cancel
            </BaseButton>
          </div>
        </form>
      </template>
    </BaseCard>
  </section>
</template>
