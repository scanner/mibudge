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
      class="mb-2 px-1 text-[11px] font-semibold uppercase tracking-wider text-fg-muted"
    >
      Change password
    </h2>

    <div class="rounded-card border border-border bg-surface px-4 py-4">
      <!-- No usable password: guide user to reset flow -->
      <div
        v-if="!session.user?.hasUsablePassword"
        class="space-y-2 text-sm text-fg"
      >
        <p>
          Your account doesn't have a password set yet — this happens when your
          account was created via an invitation.
        </p>
        <a
          href="/accounts/password/reset/"
          class="inline-block rounded-subcard bg-accent px-4 py-2.5 text-sm font-medium text-fg-on-accent hover:bg-accent-hover"
        >
          Set a password via email
        </a>
      </div>

      <template v-else>
        <!-- Success banner -->
        <div
          v-if="success"
          class="mb-4 rounded-subcard bg-success-bg px-4 py-3 text-sm text-success-fg"
          role="alert"
        >
          Password changed successfully.
        </div>

        <!-- Form-level error -->
        <div
          v-if="formError"
          class="mb-4 rounded-subcard bg-danger-bg px-4 py-3 text-sm text-danger-fg"
          role="alert"
        >
          {{ formError }}
        </div>

        <form class="space-y-4" @submit.prevent="submit">
          <!-- Current password -->
          <div>
            <label
              class="mb-1.5 block text-sm font-medium text-fg"
              for="current-password"
            >
              Current password
            </label>
            <input
              id="current-password"
              v-model="currentPassword"
              type="password"
              autocomplete="current-password"
              class="w-full rounded-subcard border px-3 py-2.5 text-sm text-fg focus:outline-none focus:ring-1"
              :class="
                fieldError('current_password')
                  ? 'border-danger-solid focus:border-danger-solid focus:ring-danger-solid'
                  : 'border-border-strong focus:border-border-focus focus:ring-border-focus'
              "
            />
            <p
              v-if="fieldError('current_password')"
              class="mt-1 text-xs text-danger-fg"
            >
              {{ fieldError("current_password") }}
            </p>
          </div>

          <!-- New password -->
          <div>
            <label
              class="mb-1.5 block text-sm font-medium text-fg"
              for="new-password"
            >
              New password
            </label>
            <input
              id="new-password"
              v-model="newPassword"
              type="password"
              autocomplete="new-password"
              class="w-full rounded-subcard border px-3 py-2.5 text-sm text-fg focus:outline-none focus:ring-1"
              :class="
                fieldError('new_password')
                  ? 'border-danger-solid focus:border-danger-solid focus:ring-danger-solid'
                  : 'border-border-strong focus:border-border-focus focus:ring-border-focus'
              "
            />
            <PasswordStrengthMeter
              :password="newPassword"
              @score="strengthScore = $event"
            />
            <p
              v-if="fieldError('new_password')"
              class="mt-1 text-xs text-danger-fg"
            >
              {{ fieldError("new_password") }}
            </p>
          </div>

          <!-- Confirm password -->
          <div>
            <label
              class="mb-1.5 block text-sm font-medium text-fg"
              for="confirm-password"
            >
              Confirm new password
            </label>
            <input
              id="confirm-password"
              v-model="confirmPassword"
              type="password"
              autocomplete="new-password"
              class="w-full rounded-subcard border px-3 py-2.5 text-sm text-fg focus:outline-none focus:ring-1"
              :class="
                fieldError('confirm_password')
                  ? 'border-danger-solid focus:border-danger-solid focus:ring-danger-solid'
                  : 'border-border-strong focus:border-border-focus focus:ring-border-focus'
              "
            />
            <p
              v-if="fieldError('confirm_password')"
              class="mt-1 text-xs text-danger-fg"
            >
              {{ fieldError("confirm_password") }}
            </p>
          </div>

          <!-- Actions -->
          <div class="flex gap-3 pt-2">
            <button
              type="submit"
              :disabled="submitDisabled"
              class="flex-1 rounded-subcard bg-accent py-2.5 text-sm font-medium text-fg-on-accent hover:bg-accent-hover disabled:opacity-50"
            >
              {{ saving ? "Saving…" : "Change password" }}
            </button>
            <button
              type="button"
              class="flex-1 rounded-subcard border border-border py-2.5 text-sm font-medium text-fg hover:bg-surface-sunken"
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
