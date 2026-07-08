<script setup lang="ts">
//
// AccountSettingsView — password change, notification preferences, and
// outgoing co-owner invitation management.
// (/app/account/settings/)
//
// This view groups all user-level "account hygiene" actions in one place.
// Invitations appear here (in addition to the per-account detail page)
// because a user may have sent invitations to several different accounts
// and wants a single place to review and cancel them all.  The per-account
// detail page shows invitations for that account only.
//
// Invitation state is loaded once on mount and is not live-updated; the
// user must reload the page to see changes made in another tab.  This is
// intentional — invitations change rarely and the complexity of polling or
// WebSocket updates is not warranted.
//

// 3rd party imports
//
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";

// app imports
//
import AppShell from "@/components/layout/AppShell.vue";
import ConfirmSheet from "@/components/shared/ConfirmSheet.vue";
import PasswordStrengthMeter from "@/components/shared/PasswordStrengthMeter.vue";
import { createApiKey, listApiKeys, revokeApiKey } from "@/api/apiKeys";
import { ApiError } from "@/api/client";
import { cancelInvitation, listMyInvitations } from "@/api/invitations";
import { changePassword } from "@/api/users";
import {
  getChannelPreferences,
  getNotificationPreferences,
  updateChannelPreference,
  updateNotificationPreference,
} from "@/api/notifications";
import { useAuthStore } from "@/stores/auth";
import type {
  APIKey,
  APIKeyCreated,
  BankAccountInvitation,
  ChannelPreference,
  NotificationPreference,
} from "@/types/api";

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
// Outgoing invitation state.
//
// myInvitations   — all PENDING invitations sent by this user across all
//                   accounts, loaded once on mount.
// inviteCancellingId — UUID of the invitation row currently being cancelled
//                   (used to show "Cancelling…" on that specific button and
//                   prevent double-clicks).  Null when no cancel is in-flight.
const myInvitations = ref<BankAccountInvitation[]>([]);
const inviteCancellingId = ref<string | null>(null);

////////////////////////////////////////////////////////////////////////
//
// API key state.
//
// apiKeys        — every key belonging to this user (active, expired,
//                   and revoked); revoked/expired keys stay listed for
//                   audit, per docs/authentication.md.
// justCreatedKey — the plaintext of a key just created, shown exactly
//                   once.  Cleared when the user dismisses the banner;
//                   it is never retrievable again after that.
// revokeTarget   — the key pending confirmation in ConfirmSheet, or
//                   null when no confirmation is in flight.
const apiKeys = ref<APIKey[]>([]);
const apiKeysLoading = ref(true);
const apiKeysError = ref<string | null>(null);
const justCreatedKey = ref<APIKeyCreated | null>(null);
const copied = ref(false);

const newKeyName = ref("");
const newKeyExpiryPreset = ref("90");
const newKeyCustomDays = ref("");
const creatingKey = ref(false);
const createKeyError = ref<string | null>(null);

const revokeTarget = ref<APIKey | null>(null);
const revokingId = ref<string | null>(null);

const EXPIRY_PRESETS: { value: string; label: string }[] = [
  { value: "30", label: "30 days" },
  { value: "60", label: "60 days" },
  { value: "90", label: "90 days" },
  { value: "365", label: "1 year" },
  { value: "custom", label: "Custom…" },
  { value: "never", label: "Never expires" },
];

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

const DELIVERY_MODE_OPTIONS: { value: NotificationPreference["delivery_mode"]; label: string }[] = [
  { value: "digest", label: "Digest" },
  { value: "immediate", label: "Immediate" },
  { value: "off", label: "Off" },
];

////////////////////////////////////////////////////////////////////////
//
onMounted(async () => {
  // Load notification preferences and outgoing invitations in parallel.
  // Invitations failures are silenced (myInvitations stays empty) so that a
  // transient API error does not degrade the password-change and notification
  // sections of this page.
  try {
    const [prefs, channels, invites] = await Promise.all([
      getNotificationPreferences(),
      getChannelPreferences(),
      listMyInvitations().catch(() => [] as BankAccountInvitation[]),
    ]);
    notifPrefs.value = prefs;
    myInvitations.value = invites;
    const email = channels.find((c: ChannelPreference) => c.channel === "email");
    if (email) emailDigestFrequency.value = email.digest_frequency;
  } catch {
    prefsError.value = "Failed to load notification preferences.";
  } finally {
    prefsLoading.value = false;
  }

  await loadApiKeys();
});

////////////////////////////////////////////////////////////////////////
//
async function setDeliveryMode(
  pref: NotificationPreference,
  mode: NotificationPreference["delivery_mode"],
): Promise<void> {
  const idx = notifPrefs.value.findIndex((p) => p.kind === pref.kind);
  if (idx === -1) return;
  // Optimistic update.
  notifPrefs.value[idx] = { ...pref, delivery_mode: mode };
  try {
    await updateNotificationPreference(pref.kind, mode);
  } catch {
    // Revert on failure.
    notifPrefs.value[idx] = pref;
    prefsError.value = "Failed to update notification preference.";
  }
}

////////////////////////////////////////////////////////////////////////
//
// doCancelInvitation — withdraw one of the current user's pending invitations.
//
// Uses optimistic removal (same rationale as BankAccountDetailView): the
// row disappears immediately and is restored only on failure.  The cancel
// endpoint requires both the account UUID and the invitation token; both
// are present in the BankAccountInvitation object returned by the API.
//
// We do not show a confirmation dialog here because cancelling an invitation
// is low-risk and easily reversible (the owner can re-invite at any time).
// Compare with delete-account, which uses ConfirmSheet because it is
// permanent and destructive.
async function doCancelInvitation(inv: BankAccountInvitation): Promise<void> {
  inviteCancellingId.value = inv.id;
  try {
    await cancelInvitation(inv.bank_account_id, inv.token);
    myInvitations.value = myInvitations.value.filter((i) => i.id !== inv.id);
  } catch {
    // Silently leave the list unchanged; the user can retry.
  } finally {
    inviteCancellingId.value = null;
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

////////////////////////////////////////////////////////////////////////
//
async function loadApiKeys(): Promise<void> {
  apiKeysLoading.value = true;
  apiKeysError.value = null;
  try {
    const page = await listApiKeys();
    apiKeys.value = page.results;
  } catch {
    apiKeysError.value = "Failed to load API keys.";
  } finally {
    apiKeysLoading.value = false;
  }
}

////////////////////////////////////////////////////////////////////////
//
// resolveExpiryDays — translate the preset selection into the
// expiry_days payload value, or null for a key that never expires.
//
function resolveExpiryDays(): number | null {
  if (newKeyExpiryPreset.value === "never") return null;
  if (newKeyExpiryPreset.value === "custom") {
    const days = Number(newKeyCustomDays.value);
    return Number.isFinite(days) && days > 0 ? days : null;
  }
  return Number(newKeyExpiryPreset.value);
}

////////////////////////////////////////////////////////////////////////
//
async function submitCreateKey(): Promise<void> {
  createKeyError.value = null;
  if (newKeyExpiryPreset.value === "custom" && !resolveExpiryDays()) {
    createKeyError.value = "Enter a valid number of days.";
    return;
  }
  creatingKey.value = true;
  try {
    const created = await createApiKey(newKeyName.value.trim(), resolveExpiryDays());
    justCreatedKey.value = created;
    copied.value = false;
    newKeyName.value = "";
    newKeyExpiryPreset.value = "90";
    newKeyCustomDays.value = "";
    await loadApiKeys();
  } catch (err) {
    if (err instanceof ApiError && err.status === 400) {
      try {
        const body = JSON.parse(err.body) as Record<string, string[]>;
        createKeyError.value = body.name?.[0] ?? "Failed to create key.";
      } catch {
        createKeyError.value = "Failed to create key.";
      }
    } else {
      createKeyError.value = "Failed to create key.";
    }
  } finally {
    creatingKey.value = false;
  }
}

////////////////////////////////////////////////////////////////////////
//
async function copyNewKey(): Promise<void> {
  if (!justCreatedKey.value) return;
  await navigator.clipboard.writeText(justCreatedKey.value.key);
  copied.value = true;
}

////////////////////////////////////////////////////////////////////////
//
// doRevokeKey — permanently revoke an API key.
//
// Unlike invitation cancellation, revocation is irreversible (a new key
// must be created to replace it), so this goes through ConfirmSheet
// rather than firing immediately.  Uses optimistic update on the
// revoked row (mark revoked_at locally) rather than removal, since
// revoked keys remain listed for audit.
async function doRevokeKey(key: APIKey): Promise<void> {
  revokingId.value = key.uuid;
  try {
    const revoked = await revokeApiKey(key.uuid);
    const idx = apiKeys.value.findIndex((k) => k.uuid === key.uuid);
    if (idx !== -1) apiKeys.value[idx] = revoked;
  } catch {
    apiKeysError.value = "Failed to revoke API key.";
  } finally {
    revokingId.value = null;
    revokeTarget.value = null;
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
          <!-- No usable password: guide user to reset flow -->
          <div
            v-if="!authStore.user?.has_usable_password"
            class="space-y-2 text-sm text-neutral-700"
          >
            <p>
              Your account doesn't have a password set yet — this happens when your account was
              created via an invitation.
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
          </template>
        </div>
      </section>

      <!-- ── API keys ─────────────────────────────────────────────── -->
      <h2 class="mb-2 mt-10 px-1 text-[11px] font-semibold uppercase tracking-wider text-secondary">
        API keys
      </h2>

      <section>
        <p class="mb-3 px-1 text-xs text-secondary">
          Long-lived credentials for importers and other 3rd-party services to access your account
          without your password. Keys get the same access a logged-in session has, except for
          account security actions.
          <a href="/docs/authentication.md" class="text-ocean-600 hover:underline" target="_blank"
            >Learn more</a
          >.
        </p>

        <!-- Error banner -->
        <div
          v-if="apiKeysError"
          class="mb-3 rounded-subcard bg-coral-50 px-4 py-3 text-sm text-coral-600"
          role="alert"
        >
          {{ apiKeysError }}
        </div>

        <!-- One-time plaintext display -->
        <div
          v-if="justCreatedKey"
          class="mb-3 rounded-card border border-mint-200 bg-mint-50 px-4 py-4"
          role="alert"
        >
          <p class="text-sm font-medium text-mint-700">
            Key created — copy it now, it won't be shown again.
          </p>
          <div class="mt-2 flex items-center gap-2">
            <code
              class="flex-1 overflow-x-auto rounded-subcard border border-mint-200 bg-white px-3 py-2 text-xs text-neutral-900"
              >{{ justCreatedKey.key }}</code
            >
            <button
              type="button"
              class="flex-none rounded-subcard border border-mint-300 px-3 py-2 text-xs font-medium text-mint-700 hover:bg-mint-100"
              @click="copyNewKey"
            >
              {{ copied ? "Copied!" : "Copy" }}
            </button>
          </div>
          <button
            type="button"
            class="mt-3 text-xs font-medium text-neutral-600 hover:text-neutral-800"
            @click="justCreatedKey = null"
          >
            Done
          </button>
        </div>

        <!-- Create key form -->
        <div class="rounded-card border border-neutral-200 bg-white px-4 py-4">
          <form class="flex flex-wrap items-end gap-3" @submit.prevent="submitCreateKey">
            <div class="min-w-[10rem] flex-1">
              <label class="mb-1.5 block text-sm font-medium text-neutral-700" for="new-key-name">
                Name
              </label>
              <input
                id="new-key-name"
                v-model="newKeyName"
                type="text"
                required
                placeholder="e.g. Bank of America importer"
                class="w-full rounded-subcard border border-neutral-200 px-3 py-2.5 text-sm text-neutral-900 focus:border-ocean-400 focus:outline-none focus:ring-1 focus:ring-ocean-400"
              />
            </div>
            <div>
              <label class="mb-1.5 block text-sm font-medium text-neutral-700" for="new-key-expiry">
                Expires
              </label>
              <select
                id="new-key-expiry"
                v-model="newKeyExpiryPreset"
                class="rounded-subcard border border-neutral-200 bg-white py-2.5 pl-2.5 pr-7 text-sm text-neutral-900 focus:border-ocean-400 focus:outline-none focus:ring-1 focus:ring-ocean-400"
              >
                <option v-for="opt in EXPIRY_PRESETS" :key="opt.value" :value="opt.value">
                  {{ opt.label }}
                </option>
              </select>
            </div>
            <div v-if="newKeyExpiryPreset === 'custom'" class="w-24">
              <label class="mb-1.5 block text-sm font-medium text-neutral-700" for="new-key-days">
                Days
              </label>
              <input
                id="new-key-days"
                v-model="newKeyCustomDays"
                type="number"
                min="1"
                class="w-full rounded-subcard border border-neutral-200 px-3 py-2.5 text-sm text-neutral-900 focus:border-ocean-400 focus:outline-none focus:ring-1 focus:ring-ocean-400"
              />
            </div>
            <button
              type="submit"
              :disabled="creatingKey || !newKeyName.trim()"
              class="rounded-subcard bg-ocean-400 px-4 py-2.5 text-sm font-medium text-white hover:bg-ocean-600 disabled:opacity-50"
            >
              {{ creatingKey ? "Creating…" : "Create key" }}
            </button>
          </form>
          <p v-if="createKeyError" class="mt-2 text-xs text-coral-600">{{ createKeyError }}</p>
        </div>

        <!-- Existing keys -->
        <div v-if="apiKeysLoading" class="mt-3 px-4 py-6 text-center text-sm text-secondary">
          Loading…
        </div>
        <div
          v-else-if="apiKeys.length > 0"
          class="mt-3 rounded-card border border-neutral-200 bg-white"
        >
          <ul class="divide-y divide-neutral-100">
            <li
              v-for="key in apiKeys"
              :key="key.uuid"
              class="flex items-start justify-between px-4 py-3"
            >
              <div>
                <p class="text-sm font-medium text-neutral-900">{{ key.name }}</p>
                <p class="mt-0.5 font-mono text-xs text-secondary">{{ key.prefix }}…</p>
                <p class="mt-0.5 text-xs text-secondary">
                  Created
                  {{
                    new Date(key.created_at).toLocaleDateString(undefined, { dateStyle: "medium" })
                  }}
                  <template v-if="key.expires_at">
                    · Expires
                    {{
                      new Date(key.expires_at).toLocaleDateString(undefined, {
                        dateStyle: "medium",
                      })
                    }}
                  </template>
                  <template v-else> · Never expires </template>
                  <template v-if="key.last_used_at">
                    · Last used
                    {{
                      new Date(key.last_used_at).toLocaleDateString(undefined, {
                        dateStyle: "medium",
                      })
                    }}
                  </template>
                </p>
              </div>
              <span v-if="key.revoked_at" class="mt-0.5 flex-none text-xs text-secondary">
                Revoked
              </span>
              <button
                v-else
                type="button"
                :disabled="revokingId === key.uuid"
                class="mt-0.5 flex-none text-xs font-medium text-coral-600 hover:text-coral-700 disabled:opacity-50"
                @click="revokeTarget = key"
              >
                {{ revokingId === key.uuid ? "Revoking…" : "Revoke" }}
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
        @confirm="revokeTarget && doRevokeKey(revokeTarget)"
      />

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

              <!-- Suppressible: 3-way delivery mode selector -->
              <select
                v-if="pref.can_suppress"
                :value="pref.delivery_mode"
                class="rounded-subcard border border-neutral-200 bg-white py-1.5 pl-2.5 pr-7 text-sm text-neutral-900 focus:border-ocean-400 focus:outline-none focus:ring-1 focus:ring-ocean-400"
                @change="
                  setDeliveryMode(
                    pref,
                    ($event.target as HTMLSelectElement)
                      .value as NotificationPreference['delivery_mode'],
                  )
                "
              >
                <option v-for="opt in DELIVERY_MODE_OPTIONS" :key="opt.value" :value="opt.value">
                  {{ opt.label }}
                </option>
              </select>

              <!-- Non-suppressible: locked indicator -->
              <span v-else class="text-xs text-secondary">Always on</span>
            </div>
          </template>
        </div>
      </section>
      <!-- ── Outgoing invitations ───────────────────────────────────── -->
      <!-- Only rendered when there is at least one pending invitation so
           the section does not appear at all for users who have never
           invited anyone or whose invitations have all been resolved. -->
      <template v-if="myInvitations.length > 0">
        <h1 class="mb-5 mt-10 text-[22px] font-medium text-neutral-900">Pending invitations</h1>

        <section>
          <div class="rounded-card border border-neutral-200 bg-white">
            <ul class="divide-y divide-neutral-100">
              <li
                v-for="inv in myInvitations"
                :key="inv.id"
                class="flex items-start justify-between px-4 py-3"
              >
                <div>
                  <!-- Account name links the invitation back to its
                       context; the invitee email is the primary identifier. -->
                  <p class="text-xs font-medium uppercase tracking-wider text-secondary">
                    {{ inv.bank_account_name }}
                  </p>
                  <p class="mt-0.5 text-sm text-neutral-900">{{ inv.invitee_email }}</p>
                  <p class="mt-0.5 text-xs text-secondary">
                    Expires
                    {{
                      new Date(inv.expires_at).toLocaleDateString(undefined, {
                        month: "short",
                        day: "numeric",
                        year: "numeric",
                      })
                    }}
                  </p>
                </div>
                <button
                  type="button"
                  :disabled="inviteCancellingId === inv.id"
                  class="mt-0.5 flex-none text-xs font-medium text-coral-600 hover:text-coral-700 disabled:opacity-50"
                  @click="doCancelInvitation(inv)"
                >
                  {{ inviteCancellingId === inv.id ? "Cancelling…" : "Cancel" }}
                </button>
              </li>
            </ul>
          </div>
        </section>
      </template>
    </div>
  </AppShell>
</template>
