<script setup lang="ts">
//
// UserProfileView — edit the current user's name and timezone.
// (UI_SPEC §4.7, /app/account/profile/)
//

// 3rd party imports
//
import { ref } from "vue";
import { useRouter } from "vue-router";

// app imports
//
import AppShell from "@/components/layout/AppShell.vue";
import { updateCurrentUser } from "@/api/users";
import { useAuthStore } from "@/stores/auth";

////////////////////////////////////////////////////////////////////////
//
const router = useRouter();
const auth = useAuthStore();

const name = ref(auth.user?.name ?? "");
const timezone = ref(auth.user?.timezone ?? "America/Los_Angeles");
const saving = ref(false);
const error = ref<string | null>(null);

////////////////////////////////////////////////////////////////////////
//
// Common IANA timezone options grouped for readability.
// The browser's Intl API validates these at runtime; the server validates
// via zoneinfo on save.
//
const TIMEZONE_OPTIONS: { value: string; label: string }[] = [
  { value: "America/New_York", label: "Eastern Time — New York" },
  { value: "America/Chicago", label: "Central Time — Chicago" },
  { value: "America/Denver", label: "Mountain Time — Denver" },
  { value: "America/Phoenix", label: "Mountain Time (no DST) — Phoenix" },
  { value: "America/Los_Angeles", label: "Pacific Time — Los Angeles" },
  { value: "America/Anchorage", label: "Alaska Time — Anchorage" },
  { value: "Pacific/Honolulu", label: "Hawaii Time — Honolulu" },
  { value: "America/Puerto_Rico", label: "Atlantic Time — Puerto Rico" },
  { value: "Europe/London", label: "GMT/BST — London" },
  { value: "Europe/Paris", label: "Central European Time — Paris" },
  { value: "Europe/Berlin", label: "Central European Time — Berlin" },
  { value: "Europe/Athens", label: "Eastern European Time — Athens" },
  { value: "Asia/Dubai", label: "Gulf Standard Time — Dubai" },
  { value: "Asia/Kolkata", label: "India Standard Time — Kolkata" },
  { value: "Asia/Bangkok", label: "Indochina Time — Bangkok" },
  { value: "Asia/Shanghai", label: "China Standard Time — Shanghai" },
  { value: "Asia/Tokyo", label: "Japan Standard Time — Tokyo" },
  { value: "Australia/Sydney", label: "AEST/AEDT — Sydney" },
  { value: "Pacific/Auckland", label: "NZST/NZDT — Auckland" },
  { value: "UTC", label: "UTC" },
];

////////////////////////////////////////////////////////////////////////
//
async function save() {
  saving.value = true;
  error.value = null;
  try {
    const updated = await updateCurrentUser({
      name: name.value,
      timezone: timezone.value,
    });
    auth.user = updated;
    router.push("/account/");
  } catch (err) {
    error.value = err instanceof Error ? err.message : "Failed to save profile.";
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <AppShell>
    <div class="mx-auto max-w-lg py-4">
      <h1 class="mb-5 text-[22px] font-medium text-neutral-900">Profile</h1>

      <div
        v-if="error"
        class="mb-4 rounded-subcard bg-coral-50 px-4 py-3 text-sm text-coral-600"
        role="alert"
      >
        {{ error }}
      </div>

      <form class="space-y-4" @submit.prevent="save">
        <!-- Name -->
        <div>
          <label class="mb-1.5 block text-sm font-medium text-neutral-700" for="profile-name">
            Name
          </label>
          <input
            id="profile-name"
            v-model="name"
            type="text"
            autocomplete="name"
            class="w-full rounded-subcard border border-neutral-200 px-3 py-2.5 text-sm text-neutral-900 placeholder-neutral-400 focus:border-ocean-400 focus:outline-none focus:ring-1 focus:ring-ocean-400"
            placeholder="Your full name"
          />
        </div>

        <!-- Username — read-only -->
        <div>
          <div class="mb-1.5 text-sm font-medium text-neutral-700">Username</div>
          <div
            class="rounded-subcard border border-neutral-200 bg-neutral-50 px-3 py-2.5 text-sm text-neutral-500"
          >
            {{ auth.user?.username }}
          </div>
        </div>

        <!-- Timezone -->
        <div>
          <label class="mb-1.5 block text-sm font-medium text-neutral-700" for="profile-timezone">
            Timezone
          </label>
          <select
            id="profile-timezone"
            v-model="timezone"
            class="w-full rounded-subcard border border-neutral-200 bg-white px-3 py-2.5 text-sm text-neutral-900 focus:border-ocean-400 focus:outline-none focus:ring-1 focus:ring-ocean-400"
          >
            <option v-for="opt in TIMEZONE_OPTIONS" :key="opt.value" :value="opt.value">
              {{ opt.label }}
            </option>
          </select>
          <p class="mt-1 text-xs text-neutral-500">
            Used to display transaction dates in your local time.
          </p>
        </div>

        <!-- Actions -->
        <div class="flex gap-3 pt-2">
          <button
            type="submit"
            :disabled="saving"
            class="flex-1 rounded-subcard bg-ocean-400 py-2.5 text-sm font-medium text-white hover:bg-ocean-600 disabled:opacity-50"
          >
            {{ saving ? "Saving…" : "Save" }}
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
  </AppShell>
</template>
