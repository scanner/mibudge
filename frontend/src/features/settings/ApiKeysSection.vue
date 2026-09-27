<script setup lang="ts">
//
// ApiKeysSection — create, list and revoke API keys.  Feature component
// (settings); state and requests live in `useApiKeys`.  A new key's
// plaintext is shown once, in a banner, until dismissed.  Revoking asks
// for confirmation because it cannot be undone.
//

// app imports
//
import ConfirmSheet from "@/components/shared/ConfirmSheet.vue";
import { formatInstantDate } from "@/domain/dates";
import { EXPIRY_PRESETS, useApiKeys } from "./useApiKeys";
import BaseButton from "@/components/base/BaseButton.vue";
import BaseFormField from "@/components/base/BaseFormField.vue";
import BaseInput from "@/components/base/BaseInput.vue";
import BaseSelect from "@/components/base/BaseSelect.vue";
import BaseSectionHeader from "@/components/base/BaseSectionHeader.vue";
import BaseCard from "@/components/base/BaseCard.vue";
import BaseListRow from "@/components/base/BaseListRow.vue";
import BaseBanner from "@/components/base/BaseBanner.vue";

////////////////////////////////////////////////////////////////////////
//
const {
  keys,
  loading,
  error,
  justCreated,
  copied,
  newKeyName,
  newKeyExpiryPreset,
  newKeyCustomDays,
  creating,
  createError,
  revokeTarget,
  revokingId,
  create,
  copyNewKey,
  dismissNewKey,
  revoke,
} = useApiKeys();

function mediumDate(iso: string): string {
  return formatInstantDate(iso, "date");
}
</script>

<template>
  <!-- ── API keys ─────────────────────────────────────────────── -->
  <BaseSectionHeader title="API keys" class="mb-2 mt-10 px-1" />

  <section>
    <p class="mb-3 px-1 text-meta text-fg-muted">
      Long-lived credentials for importers and other 3rd-party services to
      access your account without your password. Keys get the same access a
      logged-in session has, except for account security actions.
      <a
        href="/docs/authentication.md"
        class="text-fg-link hover:underline"
        target="_blank"
        >Learn more</a
      >.
    </p>

    <!-- Error banner -->
    <BaseBanner v-if="error" tone="danger" class="mb-3">
      {{ error }}
    </BaseBanner>

    <!-- One-time plaintext display -->
    <div
      v-if="justCreated"
      class="mb-3 rounded-card border border-success-border bg-success-bg px-4 py-4"
      role="alert"
    >
      <p class="text-label text-success-fg">
        Key created — copy it now, it won't be shown again.
      </p>
      <div class="mt-2 flex items-center gap-2">
        <code
          class="flex-1 overflow-x-auto rounded-control border border-success-border bg-surface px-3 py-2 text-meta text-fg"
          >{{ justCreated.plaintext }}</code
        >
        <button
          type="button"
          class="flex-none rounded-control border border-success-border px-3 py-2 text-meta font-medium text-success-fg hover:bg-success-bg"
          @click="copyNewKey"
        >
          {{ copied ? "Copied!" : "Copy" }}
        </button>
      </div>
      <button
        type="button"
        class="mt-3 text-meta font-medium text-fg-muted hover:text-fg"
        @click="dismissNewKey"
      >
        Done
      </button>
    </div>

    <!-- Create key form -->
    <BaseCard padded>
      <form class="flex flex-wrap items-end gap-3" @submit.prevent="create">
        <div class="min-w-40 flex-1">
          <BaseFormField id="new-key-name" label="Name">
            <template #default="{ id, describedBy, invalid }">
              <BaseInput
                :id="id"
                v-model="newKeyName"
                type="text"
                required
                placeholder="e.g. Bank of America importer"
                :aria-describedby="describedBy"
                :invalid="invalid"
              />
            </template>
          </BaseFormField>
        </div>
        <div>
          <BaseFormField id="new-key-expiry" label="Expires">
            <template #default="{ id, describedBy, invalid }">
              <BaseSelect
                :id="id"
                v-model="newKeyExpiryPreset"
                :aria-describedby="describedBy"
                :invalid="invalid"
                inline
              >
                <option
                  v-for="opt in EXPIRY_PRESETS"
                  :key="opt.value"
                  :value="opt.value"
                >
                  {{ opt.label }}
                </option>
              </BaseSelect>
            </template>
          </BaseFormField>
        </div>
        <div v-if="newKeyExpiryPreset === 'custom'" class="w-24">
          <BaseFormField id="new-key-days" label="Days">
            <template #default="{ id, describedBy, invalid }">
              <BaseInput
                :id="id"
                v-model="newKeyCustomDays"
                type="number"
                min="1"
                :aria-describedby="describedBy"
                :invalid="invalid"
              />
            </template>
          </BaseFormField>
        </div>
        <BaseButton
          type="submit"
          :disabled="!newKeyName.trim()"
          :loading="creating"
        >
          {{ creating ? "Creating…" : "Create key" }}
        </BaseButton>
      </form>
      <p v-if="createError" class="mt-2 text-meta text-danger-fg">
        {{ createError }}
      </p>
    </BaseCard>

    <!-- Existing keys -->
    <div
      v-if="loading"
      class="mt-3 px-4 py-6 text-center text-body-sm text-fg-muted"
    >
      Loading…
    </div>
    <div
      v-else-if="keys.length > 0"
      class="mt-3 rounded-card border border-border bg-surface"
    >
      <ul>
        <BaseListRow
          v-for="key in keys"
          as="li"
          align="start"
          class="justify-between"
          :key="key.id"
        >
          <div>
            <p class="text-label text-fg">{{ key.name }}</p>
            <p class="mt-0.5 font-mono text-amount-sm text-fg-muted">
              {{ key.prefix }}…
            </p>
            <p class="mt-0.5 text-meta text-fg-muted">
              Created
              {{ mediumDate(key.createdAt) }}
              <template v-if="key.expiresAt">
                · Expires {{ mediumDate(key.expiresAt) }}
              </template>
              <template v-else> · Never expires </template>
              <template v-if="key.lastUsedAt">
                · Last used {{ mediumDate(key.lastUsedAt) }}
              </template>
            </p>
          </div>
          <span
            v-if="key.revokedAt"
            class="mt-0.5 flex-none text-meta text-fg-muted"
          >
            Revoked
          </span>
          <BaseButton
            v-else
            variant="link-danger"
            size="sm"
            :loading="revokingId === key.id"
            class="mt-0.5 flex-none"
            @click="revokeTarget = key"
          >
            {{ revokingId === key.id ? "Revoking…" : "Revoke" }}
          </BaseButton>
        </BaseListRow>
      </ul>
    </div>
  </section>

  <ConfirmSheet
    :open="revokeTarget !== null"
    title="Revoke this API key?"
    :message="`Any service using '${revokeTarget?.name}' will immediately lose access. This cannot be undone.`"
    confirm-label="Revoke"
    @cancel="revokeTarget = null"
    @confirm="revokeTarget && revoke(revokeTarget)"
  />
</template>
