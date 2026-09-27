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
import BaseButton from "@/components/base/BaseButton.vue";
import BaseFormField from "@/components/base/BaseFormField.vue";
import BaseInput from "@/components/base/BaseInput.vue";
import BaseSelect from "@/components/base/BaseSelect.vue";
import BaseSectionHeader from "@/components/base/BaseSectionHeader.vue";
import BasePageHeader from "@/components/base/BasePageHeader.vue";
import BaseCard from "@/components/base/BaseCard.vue";
import BaseBanner from "@/components/base/BaseBanner.vue";

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
      <BasePageHeader title="Profile" />

      <BaseBanner v-if="error" tone="danger" class="mb-4">
        {{ error }}
      </BaseBanner>

      <!-- Profile form: name + timezone only -->
      <form class="space-y-4" @submit.prevent="save">
        <!-- Name -->
        <div>
          <BaseFormField id="profile-name" label="Name">
            <template #default="{ id, describedBy, invalid }">
              <BaseInput
                :id="id"
                v-model="name"
                type="text"
                autocomplete="name"
                placeholder="Your full name"
                :aria-describedby="describedBy"
                :invalid="invalid"
              />
            </template>
          </BaseFormField>
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
          <BaseFormField
            id="profile-timezone"
            label="Timezone"
            hint="Used to display transaction dates in your local time."
          >
            <template #default="{ id, describedBy, invalid }">
              <BaseSelect
                :id="id"
                v-model="timezone"
                :aria-describedby="describedBy"
                :invalid="invalid"
              >
                <option
                  v-for="opt in TIMEZONE_OPTIONS"
                  :key="opt.value"
                  :value="opt.value"
                >
                  {{ opt.label }}
                </option>
              </BaseSelect>
            </template>
          </BaseFormField>
        </div>

        <!-- Actions -->
        <div class="flex gap-3 pt-2">
          <BaseButton type="submit" :loading="saving" class="flex-1">
            {{ saving ? "Saving…" : "Save" }}
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

      <!-- Change email — separate section, never nested inside the profile form -->
      <section class="mt-8">
        <BaseSectionHeader title="Change email" class="mb-2 px-1" />

        <BaseCard padded>
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
            <BaseBanner v-if="emailSuccess" tone="success">
              Check your new address for a verification link, and your current
              address for a security notice.
            </BaseBanner>

            <template v-else>
              <!-- Error -->
              <BaseBanner v-if="emailError" tone="danger" class="mb-3">
                {{ emailError }}
              </BaseBanner>

              <form class="flex gap-2" @submit.prevent="submitEmailChange">
                <BaseInput
                  v-model="newEmail"
                  type="email"
                  autocomplete="email"
                  placeholder="New email address"
                  required
                  class="min-w-0 flex-1"
                  inline
                />
                <BaseButton
                  type="submit"
                  :disabled="!newEmail"
                  :loading="emailSaving"
                >
                  {{ emailSaving ? "Sending…" : "Send link" }}
                </BaseButton>
              </form>
              <p class="mt-1.5 text-meta text-fg-muted">
                A verification link will be sent to the new address. Your
                current address will receive a security notice with a link to
                cancel the change for 7 days after confirmation.
              </p>
            </template>
          </template>
        </BaseCard>
      </section>
    </div>
  </AppShell>
</template>
