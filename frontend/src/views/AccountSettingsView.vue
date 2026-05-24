<script setup lang="ts">
//
// AccountSettingsView — password change and (future) notification preferences.
// (/app/account/settings/)
//

// 3rd party imports
//
import { ref } from "vue";
import { useRouter } from "vue-router";

// app imports
//
import AppShell from "@/components/layout/AppShell.vue";
import PasswordStrengthMeter from "@/components/shared/PasswordStrengthMeter.vue";
import { ApiError } from "@/api/client";
import { changePassword } from "@/api/users";

////////////////////////////////////////////////////////////////////////
//
const router = useRouter();

////////////////////////////////////////////////////////////////////////
//
// Password change form state.
//
const currentPassword = ref("");
const newPassword = ref("");
const confirmPassword = ref("");
const strengthScore = ref<number | null>(null);
const saving = ref(false);
const success = ref(false);

// Field-level and form-level errors from the API.
const fieldErrors = ref<Record<string, string[]>>({});
const formError = ref<string | null>(null);

////////////////////////////////////////////////////////////////////////
//
function fieldError(field: string): string | null {
  const msgs = fieldErrors.value[field];
  return msgs?.length ? msgs[0] : null;
}

////////////////////////////////////////////////////////////////////////
//
async function submitPasswordChange(): Promise<void> {
  saving.value = true;
  success.value = false;
  formError.value = null;
  fieldErrors.value = {};

  try {
    await changePassword({
      current_password: currentPassword.value,
      new_password: newPassword.value,
      confirm_password: confirmPassword.value,
    });
    success.value = true;
    currentPassword.value = "";
    newPassword.value = "";
    confirmPassword.value = "";
    strengthScore.value = null;
  } catch (err) {
    if (err instanceof ApiError && err.status === 400) {
      try {
        fieldErrors.value = JSON.parse(err.body) as Record<string, string[]>;
      } catch {
        formError.value = "Request failed. Please try again.";
      }
    } else {
      formError.value = err instanceof Error ? err.message : "Failed to change password.";
    }
  } finally {
    saving.value = false;
  }
}

////////////////////////////////////////////////////////////////////////
//
// Disable submit until the new password meets the strength threshold.
//
const submitDisabled = (): boolean =>
  saving.value || strengthScore.value === null || strengthScore.value < 2;
</script>

<template>
  <AppShell>
    <div class="mx-auto max-w-lg py-4">
      <h1 class="mb-5 text-[22px] font-medium text-neutral-900">Security</h1>

      <!-- Password change card -->
      <section>
        <h2 class="mb-2 px-1 text-[11px] font-semibold uppercase tracking-wider text-secondary">
          Change password
        </h2>

        <div class="rounded-card border border-neutral-200 bg-white px-4 py-4">
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

          <form class="space-y-4" @submit.prevent="submitPasswordChange">
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
              <p v-if="fieldError('current_password')" class="mt-1 text-xs text-coral-600">
                {{ fieldError("current_password") }}
              </p>
            </div>

            <!-- New password -->
            <div>
              <label class="mb-1.5 block text-sm font-medium text-neutral-700" for="new-password">
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
              <PasswordStrengthMeter :password="newPassword" @score="strengthScore = $event" />
              <p v-if="fieldError('new_password')" class="mt-1 text-xs text-coral-600">
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
              <p v-if="fieldError('confirm_password')" class="mt-1 text-xs text-coral-600">
                {{ fieldError("confirm_password") }}
              </p>
            </div>

            <!-- Actions -->
            <div class="flex gap-3 pt-2">
              <button
                type="submit"
                :disabled="submitDisabled()"
                class="flex-1 rounded-subcard bg-ocean-400 py-2.5 text-sm font-medium text-white hover:bg-ocean-600 disabled:opacity-50"
              >
                {{ saving ? "Saving…" : "Change password" }}
              </button>
              <button
                type="button"
                class="flex-1 rounded-subcard border border-neutral-200 py-2.5 text-sm font-medium text-neutral-700 hover:bg-neutral-50"
                @click="router.push('/account/')"
              >
                Cancel
              </button>
            </div>
          </form>
        </div>
      </section>
    </div>
  </AppShell>
</template>
