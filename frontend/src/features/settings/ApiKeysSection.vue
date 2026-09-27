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
  return formatInstantDate(iso, { dateStyle: "medium" });
}
</script>

<template>
  <!-- ── API keys ─────────────────────────────────────────────── -->
  <h2
    class="mb-2 mt-10 px-1 text-[11px] font-semibold uppercase tracking-wider text-fg-muted"
  >
    API keys
  </h2>

  <section>
    <p class="mb-3 px-1 text-xs text-fg-muted">
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
    <div
      v-if="error"
      class="mb-3 rounded-subcard bg-danger-bg px-4 py-3 text-sm text-danger-fg"
      role="alert"
    >
      {{ error }}
    </div>

    <!-- One-time plaintext display -->
    <div
      v-if="justCreated"
      class="mb-3 rounded-card border border-success-border bg-success-bg px-4 py-4"
      role="alert"
    >
      <p class="text-sm font-medium text-success-fg">
        Key created — copy it now, it won't be shown again.
      </p>
      <div class="mt-2 flex items-center gap-2">
        <code
          class="flex-1 overflow-x-auto rounded-subcard border border-success-border bg-surface px-3 py-2 text-xs text-fg"
          >{{ justCreated.plaintext }}</code
        >
        <button
          type="button"
          class="flex-none rounded-subcard border border-success-border px-3 py-2 text-xs font-medium text-success-fg hover:bg-success-bg"
          @click="copyNewKey"
        >
          {{ copied ? "Copied!" : "Copy" }}
        </button>
      </div>
      <button
        type="button"
        class="mt-3 text-xs font-medium text-fg-muted hover:text-fg"
        @click="dismissNewKey"
      >
        Done
      </button>
    </div>

    <!-- Create key form -->
    <div class="rounded-card border border-border bg-surface px-4 py-4">
      <form class="flex flex-wrap items-end gap-3" @submit.prevent="create">
        <div class="min-w-[10rem] flex-1">
          <label
            class="mb-1.5 block text-sm font-medium text-fg"
            for="new-key-name"
          >
            Name
          </label>
          <input
            id="new-key-name"
            v-model="newKeyName"
            type="text"
            required
            placeholder="e.g. Bank of America importer"
            class="w-full rounded-subcard border border-border-strong px-3 py-2.5 text-sm text-fg focus:border-border-focus focus:outline-none focus:ring-1 focus:ring-border-focus"
          />
        </div>
        <div>
          <label
            class="mb-1.5 block text-sm font-medium text-fg"
            for="new-key-expiry"
          >
            Expires
          </label>
          <select
            id="new-key-expiry"
            v-model="newKeyExpiryPreset"
            class="rounded-subcard border border-border-strong bg-surface py-2.5 pl-2.5 pr-7 text-sm text-fg focus:border-border-focus focus:outline-none focus:ring-1 focus:ring-border-focus"
          >
            <option
              v-for="opt in EXPIRY_PRESETS"
              :key="opt.value"
              :value="opt.value"
            >
              {{ opt.label }}
            </option>
          </select>
        </div>
        <div v-if="newKeyExpiryPreset === 'custom'" class="w-24">
          <label
            class="mb-1.5 block text-sm font-medium text-fg"
            for="new-key-days"
          >
            Days
          </label>
          <input
            id="new-key-days"
            v-model="newKeyCustomDays"
            type="number"
            min="1"
            class="w-full rounded-subcard border border-border-strong px-3 py-2.5 text-sm text-fg focus:border-border-focus focus:outline-none focus:ring-1 focus:ring-border-focus"
          />
        </div>
        <button
          type="submit"
          :disabled="creating || !newKeyName.trim()"
          class="rounded-subcard bg-accent px-4 py-2.5 text-sm font-medium text-fg-on-accent hover:bg-accent-hover disabled:opacity-50"
        >
          {{ creating ? "Creating…" : "Create key" }}
        </button>
      </form>
      <p v-if="createError" class="mt-2 text-xs text-danger-fg">
        {{ createError }}
      </p>
    </div>

    <!-- Existing keys -->
    <div
      v-if="loading"
      class="mt-3 px-4 py-6 text-center text-sm text-fg-muted"
    >
      Loading…
    </div>
    <div
      v-else-if="keys.length > 0"
      class="mt-3 rounded-card border border-border bg-surface"
    >
      <ul class="divide-y divide-border-subtle">
        <li
          v-for="key in keys"
          :key="key.id"
          class="flex items-start justify-between px-4 py-3"
        >
          <div>
            <p class="text-sm font-medium text-fg">{{ key.name }}</p>
            <p class="mt-0.5 font-mono text-xs text-fg-muted">
              {{ key.prefix }}…
            </p>
            <p class="mt-0.5 text-xs text-fg-muted">
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
            class="mt-0.5 flex-none text-xs text-fg-muted"
          >
            Revoked
          </span>
          <button
            v-else
            type="button"
            :disabled="revokingId === key.id"
            class="mt-0.5 flex-none text-xs font-medium text-danger-fg hover:text-danger-solid-hover disabled:opacity-50"
            @click="revokeTarget = key"
          >
            {{ revokingId === key.id ? "Revoking…" : "Revoke" }}
          </button>
        </li>
      </ul>
    </div>
  </section>

  <ConfirmSheet
    :open="revokeTarget !== null"
    title="Revoke this API key?"
    :message="`Any service using '${revokeTarget?.name}' will immediately lose access. This cannot be undone.`"
    confirm-label="Revoke"
    tone="coral"
    @cancel="revokeTarget = null"
    @confirm="revokeTarget && revoke(revokeTarget)"
  />
</template>
