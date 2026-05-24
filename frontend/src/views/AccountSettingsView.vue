<script setup lang="ts">
//
// AccountSettingsView — password change and notification preferences.
// (/app/account/settings/)
//

// 3rd party imports
//
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";

// app imports
//
import AppShell from "@/components/layout/AppShell.vue";
import PasswordStrengthMeter from "@/components/shared/PasswordStrengthMeter.vue";
import { ApiError } from "@/api/client";
import { changePassword } from "@/api/users";
import {
  getChannelPreferences,
  getNotificationPreferences,
  updateChannelPreference,
  updateNotificationPreference,
} from "@/api/notifications";
import { useAuthStore } from "@/stores/auth";
import type { ChannelPreference, NotificationPreference } from "@/types/api";

////////////////////////////////////////////////////////////////////////
//
const authStore = useAuthStore();

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

////////////////////////////////////////////////////////////////////////
//
// Notification preferences state.
//
const notifPrefs = ref<NotificationPreference[]>([]);
const emailDigestFrequency = ref("daily_evening");
const prefsLoading = ref(true);
const prefsError = ref<string | null>(null);

const DIGEST_OPTIONS: { value: string; label: string }[] = [
  { value: "daily_morning", label: "Once daily (morning, ~7 am)" },
  { value: "daily_evening", label: "Once daily (evening, ~6 pm)" },
  { value: "twice_daily", label: "Twice daily (morning + evening)" },
  { value: "weekly_friday", label: "Weekly on Friday" },
  { value: "weekly_saturday", label: "Weekly on Saturday" },
  { value: "weekly_sunday", label: "Weekly on Sunday" },
];

////////////////////////////////////////////////////////////////////////
//
onMounted(async () => {
  try {
    const [prefs, channels] = await Promise.all([
      getNotificationPreferences(),
      getChannelPreferences(),
    ]);
    notifPrefs.value = prefs;
    const email = channels.find((c: ChannelPreference) => c.channel === "email");
    if (email) emailDigestFrequency.value = email.digest_frequency;
  } catch {
    prefsError.value = "Failed to load notification preferences.";
  } finally {
    prefsLoading.value = false;
  }
});

////////////////////////////////////////////////////////////////////////
//
async function togglePref(pref: NotificationPreference): Promise<void> {
  const newEnabled = !pref.enabled;
  const idx = notifPrefs.value.findIndex((p) => p.kind === pref.kind);
  if (idx === -1) return;
  // Optimistic update.
  notifPrefs.value[idx] = { ...pref, enabled: newEnabled };
  try {
    await updateNotificationPreference(pref.kind, newEnabled);
  } catch {
    // Revert on failure.
    notifPrefs.value[idx] = pref;
    prefsError.value = "Failed to update notification preference.";
  }
}

////////////////////////////////////////////////////////////////////////
//
async function saveEmailDigest(): Promise<void> {
  prefsError.value = null;
  try {
    await updateChannelPreference("email", emailDigestFrequency.value);
  } catch {
    prefsError.value = "Failed to save email preference.";
  }
}
</script>

<template>
  <AppShell>
    <div class="mx-auto max-w-lg py-4">
      <!-- ── Security ─────────────────────────────────────────────── -->
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

      <!-- ── Notifications ────────────────────────────────────────── -->
      <h1 class="mb-5 mt-10 text-[22px] font-medium text-neutral-900">Notifications</h1>

      <section>
        <!-- Error banner -->
        <div
          v-if="prefsError"
          class="mb-3 rounded-subcard bg-coral-50 px-4 py-3 text-sm text-coral-600"
          role="alert"
        >
          {{ prefsError }}
        </div>

        <div class="rounded-card border border-neutral-200 bg-white">
          <!-- Loading skeleton -->
          <div v-if="prefsLoading" class="px-4 py-6 text-center text-sm text-secondary">
            Loading…
          </div>

          <template v-else>
            <!-- Notification destination (email only for now) -->
            <div class="border-b border-neutral-100 px-4 py-3">
              <p class="text-xs text-secondary">Notifications are sent to</p>
              <p class="mt-0.5 text-sm font-medium text-neutral-900">
                {{ authStore.user?.email }}
              </p>
            </div>

            <!-- Email digest frequency (only email channel is active) -->
            <div class="flex items-center justify-between border-b border-neutral-100 px-4 py-4">
              <div>
                <p class="text-sm font-medium text-neutral-900">Email digest</p>
                <p class="mt-0.5 text-xs text-secondary">How often to receive email digests</p>
              </div>
              <select
                v-model="emailDigestFrequency"
                class="rounded-subcard border border-neutral-200 bg-white py-1.5 pl-2.5 pr-7 text-sm text-neutral-900 focus:border-ocean-400 focus:outline-none focus:ring-1 focus:ring-ocean-400"
                @change="saveEmailDigest"
              >
                <option v-for="opt in DIGEST_OPTIONS" :key="opt.value" :value="opt.value">
                  {{ opt.label }}
                </option>
              </select>
            </div>

            <!-- Per-kind toggles -->
            <div
              v-for="pref in notifPrefs"
              :key="pref.kind"
              class="flex items-center justify-between border-b border-neutral-100 px-4 py-3 last:border-b-0"
            >
              <span class="text-sm text-neutral-700">{{ pref.display_name }}</span>

              <!-- Suppressible: interactive toggle -->
              <label
                v-if="pref.can_suppress"
                class="relative inline-flex cursor-pointer items-center"
              >
                <input
                  type="checkbox"
                  class="peer sr-only"
                  :checked="pref.enabled"
                  @change="togglePref(pref)"
                />
                <div
                  class="peer h-5 w-9 rounded-full bg-neutral-200 transition-colors after:absolute after:left-[2px] after:top-[2px] after:h-4 after:w-4 after:rounded-full after:bg-white after:transition-all after:content-[''] peer-checked:bg-ocean-400 peer-checked:after:translate-x-4"
                ></div>
              </label>

              <!-- Non-suppressible: locked indicator -->
              <span v-else class="text-xs text-secondary">Always on</span>
            </div>
          </template>
        </div>
      </section>
    </div>
  </AppShell>
</template>
