<script setup lang="ts">
//
// UserProfileView — edit the current user's name and timezone, and
// request an email change.  (UI_SPEC §4.7)  Route shell over
// `useProfileForm`.
//

// 3rd party imports
//
import { useRouter } from "vue-router";

// app imports
//
import {
  TIMEZONE_OPTIONS,
  useProfileForm,
} from "@/features/settings/useProfileForm";
import AppShell from "@/features/shell/AppShell.vue";
import { useSessionStore } from "@/stores/session";

////////////////////////////////////////////////////////////////////////
//
const router = useRouter();
const auth = useSessionStore();

const {
  name,
  timezone,
  saving,
  error,
  save: saveProfile,
  newEmail,
  emailSaving,
  emailSuccess,
  emailError,
  requestEmailChange: submitEmailChange,
} = useProfileForm();

async function save() {
  if (await saveProfile()) router.push({ name: "account" });
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

      <!-- Profile form: name + timezone only -->
      <form class="space-y-4" @submit.prevent="save">
        <!-- Name -->
        <div>
          <label
            class="mb-1.5 block text-sm font-medium text-neutral-700"
            for="profile-name"
          >
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

        <!-- Email — read-only -->
        <div>
          <div class="mb-1.5 text-sm font-medium text-neutral-700">Email</div>
          <div
            class="rounded-subcard border border-neutral-200 bg-neutral-50 px-3 py-2.5 text-sm text-neutral-500"
          >
            {{ auth.user?.email }}
          </div>
        </div>

        <!-- Timezone -->
        <div>
          <label
            class="mb-1.5 block text-sm font-medium text-neutral-700"
            for="profile-timezone"
          >
            Timezone
          </label>
          <select
            id="profile-timezone"
            v-model="timezone"
            class="w-full rounded-subcard border border-neutral-200 bg-white px-3 py-2.5 text-sm text-neutral-900 focus:border-ocean-400 focus:outline-none focus:ring-1 focus:ring-ocean-400"
          >
            <option
              v-for="opt in TIMEZONE_OPTIONS"
              :key="opt.value"
              :value="opt.value"
            >
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
            @click="router.push({ name: 'account' })"
          >
            Cancel
          </button>
        </div>
      </form>

      <!-- Change email — separate section, never nested inside the profile form -->
      <section class="mt-8">
        <h2
          class="mb-2 px-1 text-[11px] font-semibold uppercase tracking-wider text-secondary"
        >
          Change email
        </h2>

        <div class="rounded-card border border-neutral-200 bg-white px-4 py-4">
          <!-- No usable password -->
          <div
            v-if="!auth.user?.hasUsablePassword"
            class="text-sm text-neutral-500"
          >
            Your account doesn't have a password set yet.
            <a
              href="/accounts/password/reset/"
              class="ml-1 text-ocean-600 underline hover:text-ocean-800"
            >
              Set a password via email
            </a>
            to unlock this feature.
          </div>

          <template v-else>
            <!-- Success -->
            <div
              v-if="emailSuccess"
              class="rounded-subcard bg-mint-50 px-3 py-3 text-sm text-mint-600"
              role="alert"
            >
              Check your new address for a verification link, and your current
              address for a security notice.
            </div>

            <template v-else>
              <!-- Error -->
              <div
                v-if="emailError"
                class="mb-3 rounded-subcard bg-coral-50 px-3 py-3 text-sm text-coral-600"
                role="alert"
              >
                {{ emailError }}
              </div>

              <form class="flex gap-2" @submit.prevent="submitEmailChange">
                <input
                  v-model="newEmail"
                  type="email"
                  autocomplete="email"
                  placeholder="New email address"
                  required
                  class="min-w-0 flex-1 rounded-subcard border border-neutral-200 px-3 py-2.5 text-sm text-neutral-900 placeholder-neutral-400 focus:border-ocean-400 focus:outline-none focus:ring-1 focus:ring-ocean-400"
                />
                <button
                  type="submit"
                  :disabled="emailSaving || !newEmail"
                  class="rounded-subcard bg-ocean-400 px-4 py-2.5 text-sm font-medium text-white hover:bg-ocean-600 disabled:opacity-50"
                >
                  {{ emailSaving ? "Sending…" : "Send link" }}
                </button>
              </form>
              <p class="mt-1.5 text-xs text-neutral-500">
                A verification link will be sent to the new address. Your
                current address will receive a security notice with a link to
                cancel the change for 7 days after confirmation.
              </p>
            </template>
          </template>
        </div>
      </section>
    </div>
  </AppShell>
</template>
