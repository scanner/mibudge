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
    <h2
      class="mb-2 px-1 text-[11px] font-semibold uppercase tracking-wider text-secondary"
    >
      Change password
    </h2>

    <div class="rounded-card border border-neutral-200 bg-white px-4 py-4">
      <!-- No usable password: guide user to reset flow -->
      <div
        v-if="!session.user?.hasUsablePassword"
        class="space-y-2 text-sm text-neutral-700"
      >
        <p>
          Your account doesn't have a password set yet — this happens when your
          account was created via an invitation.
        </p>
        <a
          href="/accounts/password/reset/"
          class="inline-block rounded-subcard bg-ocean-400 px-4 py-2.5 text-sm font-medium text-white hover:bg-ocean-600"
        >
          Set a password via email
        </a>
      </div>

      <template v-else>
        <!-- Success banner -->
        <div
          v-if="success"
          class="mb-4 rounded-subcard bg-mint-50 px-4 py-3 text-sm text-mint-600"
          role="alert"
        >
          Password changed successfully.
        </div>

        <!-- Form-level error -->
        <div
          v-if="formError"
          class="mb-4 rounded-subcard bg-coral-50 px-4 py-3 text-sm text-coral-600"
          role="alert"
        >
          {{ formError }}
        </div>

        <form class="space-y-4" @submit.prevent="submit">
          <!-- Current password -->
          <div>
            <label
              class="mb-1.5 block text-sm font-medium text-neutral-700"
              for="current-password"
            >
              Current password
            </label>
            <input
              id="current-password"
              v-model="currentPassword"
              type="password"
              autocomplete="current-password"
              class="w-full rounded-subcard border px-3 py-2.5 text-sm text-neutral-900 focus:outline-none focus:ring-1"
              :class="
                fieldError('current_password')
                  ? 'border-coral-400 focus:border-coral-400 focus:ring-coral-400'
                  : 'border-neutral-200 focus:border-ocean-400 focus:ring-ocean-400'
              "
            />
            <p
              v-if="fieldError('current_password')"
              class="mt-1 text-xs text-coral-600"
            >
              {{ fieldError("current_password") }}
            </p>
          </div>

          <!-- New password -->
          <div>
            <label
              class="mb-1.5 block text-sm font-medium text-neutral-700"
              for="new-password"
            >
              New password
            </label>
            <input
              id="new-password"
              v-model="newPassword"
              type="password"
              autocomplete="new-password"
              class="w-full rounded-subcard border px-3 py-2.5 text-sm text-neutral-900 focus:outline-none focus:ring-1"
              :class="
                fieldError('new_password')
                  ? 'border-coral-400 focus:border-coral-400 focus:ring-coral-400'
                  : 'border-neutral-200 focus:border-ocean-400 focus:ring-ocean-400'
              "
            />
            <PasswordStrengthMeter
              :password="newPassword"
              @score="strengthScore = $event"
            />
            <p
              v-if="fieldError('new_password')"
              class="mt-1 text-xs text-coral-600"
            >
              {{ fieldError("new_password") }}
            </p>
          </div>

          <!-- Confirm password -->
          <div>
            <label
              class="mb-1.5 block text-sm font-medium text-neutral-700"
              for="confirm-password"
            >
              Confirm new password
            </label>
            <input
              id="confirm-password"
              v-model="confirmPassword"
              type="password"
              autocomplete="new-password"
              class="w-full rounded-subcard border px-3 py-2.5 text-sm text-neutral-900 focus:outline-none focus:ring-1"
              :class="
                fieldError('confirm_password')
                  ? 'border-coral-400 focus:border-coral-400 focus:ring-coral-400'
                  : 'border-neutral-200 focus:border-ocean-400 focus:ring-ocean-400'
              "
            />
            <p
              v-if="fieldError('confirm_password')"
              class="mt-1 text-xs text-coral-600"
            >
              {{ fieldError("confirm_password") }}
            </p>
          </div>

          <!-- Actions -->
          <div class="flex gap-3 pt-2">
            <button
              type="submit"
              :disabled="submitDisabled"
              class="flex-1 rounded-subcard bg-ocean-400 py-2.5 text-sm font-medium text-white hover:bg-ocean-600 disabled:opacity-50"
            >
              {{ saving ? "Saving…" : "Change password" }}
            </button>
            <button
              type="button"
              class="flex-1 rounded-subcard border border-neutral-200 py-2.5 text-sm font-medium text-neutral-700 hover:bg-neutral-50"
              @click="router.push({ name: 'account' })"
            >
              Cancel
            </button>
          </div>
        </form>
      </template>
    </div>
  </section>
</template>
