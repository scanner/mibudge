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
      <h1 class="mb-5 text-page-title text-fg">Profile</h1>

      <div
        v-if="error"
        class="mb-4 rounded-control bg-danger-bg px-4 py-3 text-body-sm text-danger-fg"
        role="alert"
      >
        {{ error }}
      </div>

      <!-- Profile form: name + timezone only -->
      <form class="space-y-4" @submit.prevent="save">
        <!-- Name -->
        <div>
          <label class="mb-1.5 block text-label text-fg" for="profile-name">
            Name
          </label>
          <input
            id="profile-name"
            v-model="name"
            type="text"
            autocomplete="name"
            class="w-full rounded-control border border-border-strong px-3 py-2.5 text-input text-fg placeholder-fg-subtle focus:border-border-focus focus:outline-none focus:ring-1 focus:ring-border-focus"
            placeholder="Your full name"
          />
        </div>

        <!-- Email — read-only -->
        <div>
          <div class="mb-1.5 text-label text-fg">Email</div>
          <div
            class="rounded-control border border-border bg-surface-sunken px-3 py-2.5 text-body-sm text-fg-muted"
          >
            {{ auth.user?.email }}
          </div>
        </div>

        <!-- Timezone -->
        <div>
          <label class="mb-1.5 block text-label text-fg" for="profile-timezone">
            Timezone
          </label>
          <select
            id="profile-timezone"
            v-model="timezone"
            class="w-full rounded-control border border-border-strong bg-surface px-3 py-2.5 text-input text-fg focus:border-border-focus focus:outline-none focus:ring-1 focus:ring-border-focus"
          >
            <option
              v-for="opt in TIMEZONE_OPTIONS"
              :key="opt.value"
              :value="opt.value"
            >
              {{ opt.label }}
            </option>
          </select>
          <p class="mt-1 text-meta text-fg-muted">
            Used to display transaction dates in your local time.
          </p>
        </div>

        <!-- Actions -->
        <div class="flex gap-3 pt-2">
          <button
            type="submit"
            :disabled="saving"
            class="flex-1 rounded-control bg-accent py-2.5 text-label text-fg-on-accent hover:bg-accent-hover disabled:opacity-50"
          >
            {{ saving ? "Saving…" : "Save" }}
          </button>
          <button
            type="button"
            class="flex-1 rounded-control border border-border py-2.5 text-label text-fg hover:bg-surface-sunken"
            @click="router.push({ name: 'account' })"
          >
            Cancel
          </button>
        </div>
      </form>

      <!-- Change email — separate section, never nested inside the profile form -->
      <section class="mt-8">
        <h2 class="mb-2 px-1 text-overline uppercase text-fg-muted">
          Change email
        </h2>

        <div class="rounded-card border border-border bg-surface px-4 py-4">
          <!-- No usable password -->
          <div
            v-if="!auth.user?.hasUsablePassword"
            class="text-body-sm text-fg-muted"
          >
            Your account doesn't have a password set yet.
            <a
              href="/accounts/password/reset/"
              class="ml-1 text-fg-link underline hover:text-accent-hover"
            >
              Set a password via email
            </a>
            to unlock this feature.
          </div>

          <template v-else>
            <!-- Success -->
            <div
              v-if="emailSuccess"
              class="rounded-control bg-success-bg px-3 py-3 text-body-sm text-success-fg"
              role="alert"
            >
              Check your new address for a verification link, and your current
              address for a security notice.
            </div>

            <template v-else>
              <!-- Error -->
              <div
                v-if="emailError"
                class="mb-3 rounded-control bg-danger-bg px-3 py-3 text-body-sm text-danger-fg"
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
                  class="min-w-0 flex-1 rounded-control border border-border-strong px-3 py-2.5 text-input text-fg placeholder-fg-subtle focus:border-border-focus focus:outline-none focus:ring-1 focus:ring-border-focus"
                />
                <button
                  type="submit"
                  :disabled="emailSaving || !newEmail"
                  class="rounded-control bg-accent px-4 py-2.5 text-label text-fg-on-accent hover:bg-accent-hover disabled:opacity-50"
                >
                  {{ emailSaving ? "Sending…" : "Send link" }}
                </button>
              </form>
              <p class="mt-1.5 text-meta text-fg-muted">
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
