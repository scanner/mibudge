<script setup lang="ts">
//
// OAuth2AppsView — register and manage your own OAuth2 applications.
// (/app/account/oauth2-apps/)
//
// These are apps you *register* so they can be granted delegated access
// to accounts (yours, or — once staff promote them — everyone's).  This
// is a different surface from the "Authorized apps" page (apps you have
// granted access to); see docs/authentication.md.
//
// Backend divergences from the rest of the API worth remembering here:
//   - the lookup key is `client_id`, not a UUID;
//   - timestamps are `created`/`updated` (django-oauth-toolkit names);
//   - `client_secret` is returned exactly once, at registration, and
//     only for confidential clients (public clients get null and use
//     PKCE instead);
//   - `visibility`/`status` are staff-managed and read-only here.
//

// 3rd party imports
//
import { IconArrowLeft, IconPlus, IconTrash } from "@tabler/icons-vue";
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";

// app imports
//
import AppShell from "@/components/layout/AppShell.vue";
import ConfirmSheet from "@/components/shared/ConfirmSheet.vue";
import EmptyState from "@/components/shared/EmptyState.vue";
import { ApiError } from "@/api/client";
import {
  deregisterOAuth2App,
  listOAuth2Apps,
  registerOAuth2App,
  updateOAuth2App,
} from "@/api/oauth2Apps";
import type {
  OAuth2Application,
  OAuth2ApplicationCreated,
  OAuth2ClientType,
  OAuth2Status,
  OAuth2Visibility,
} from "@/types/api";

////////////////////////////////////////////////////////////////////////
//
const router = useRouter();

////////////////////////////////////////////////////////////////////////
//
// App list state.
//
const apps = ref<OAuth2Application[]>([]);
const loading = ref(true);
const loadError = ref<string | null>(null);

////////////////////////////////////////////////////////////////////////
//
// Registration form state.  Hidden behind a button so the (bulky)
// redirect-URI editor does not dominate the page when idle.  Public is
// the default client type — native, mobile, desktop and MCP clients (the
// common case) cannot keep a secret and authenticate with PKCE.
//
const showCreateForm = ref(false);
const newName = ref("");
const newClientType = ref<OAuth2ClientType>("public");
const newRedirectUris = ref<string[]>([""]);
const creating = ref(false);
const createError = ref<string | null>(null);

////////////////////////////////////////////////////////////////////////
//
// One-time registration result: the ONLY moment the client secret exists
// in plaintext (confidential clients only; null for public).  The
// client_id is stable and always retrievable, but we surface it here too
// so a freshly registered app can be wired up without a page reload.
//
const justRegistered = ref<OAuth2ApplicationCreated | null>(null);
const copiedSecret = ref(false);
const copiedId = ref(false);

////////////////////////////////////////////////////////////////////////
//
// Inline edit state — one app at a time.  client_type is create-only, so
// only name and redirect URIs are editable.
//
const editingId = ref<string | null>(null);
const editName = ref("");
const editRedirectUris = ref<string[]>([""]);
const savingEdit = ref(false);
const editError = ref<string | null>(null);

////////////////////////////////////////////////////////////////////////
//
// Deregistration confirmation.
//
const deregisterTarget = ref<OAuth2Application | null>(null);
const deregisteringId = ref<string | null>(null);

////////////////////////////////////////////////////////////////////////
//
const CLIENT_TYPE_LABELS: Record<OAuth2ClientType, string> = {
  public: "Public",
  confidential: "Confidential",
};

const VISIBILITY_LABELS: Record<OAuth2Visibility, string> = {
  private: "Private",
  global: "Global",
};

const STATUS_LABELS: Record<OAuth2Status, string> = {
  testing: "Testing",
  validation: "Validation",
  published: "Published",
};

////////////////////////////////////////////////////////////////////////
//
onMounted(loadApps);

async function loadApps(): Promise<void> {
  loading.value = true;
  loadError.value = null;
  try {
    const page = await listOAuth2Apps();
    apps.value = page.results;
  } catch {
    loadError.value = "Failed to load applications.";
  } finally {
    loading.value = false;
  }
}

////////////////////////////////////////////////////////////////////////
//
// extractError — pull the most actionable message out of a DRF 400.
//
// The backend's redirect-URI messages are deliberately specific (e.g.
// "use the loopback IP literal instead of localhost"), so we surface
// field errors verbatim rather than collapsing them into a generic
// "failed".  Prefer redirect_uris, then name, then a form-level detail.
//
function extractError(err: unknown, fallback: string): string {
  if (!(err instanceof ApiError) || err.status !== 400) return fallback;
  let body: unknown;
  try {
    body = JSON.parse(err.body);
  } catch {
    return fallback;
  }
  if (typeof body !== "object" || body === null) return fallback;
  const record = body as Record<string, unknown>;

  const flatten = (value: unknown): string | null => {
    if (typeof value === "string") return value;
    if (Array.isArray(value)) {
      for (const item of value) {
        const msg = flatten(item);
        if (msg) return msg;
      }
      return null;
    }
    if (typeof value === "object" && value !== null) {
      for (const item of Object.values(value)) {
        const msg = flatten(item);
        if (msg) return msg;
      }
    }
    return null;
  };

  for (const field of ["redirect_uris", "name", "client_type", "detail"]) {
    const msg = flatten(record[field]);
    if (msg) return msg;
  }
  return fallback;
}

////////////////////////////////////////////////////////////////////////
//
// Redirect-URI list editors.  The list always keeps at least one row so
// there is a field to type into; blanks are stripped before submit.
//
function addUri(list: string[]): void {
  list.push("");
}

function removeUri(list: string[], idx: number): void {
  list.splice(idx, 1);
  if (list.length === 0) list.push("");
}

function cleanUris(list: string[]): string[] {
  return list.map((u) => u.trim()).filter(Boolean);
}

////////////////////////////////////////////////////////////////////////
//
function openCreateForm(): void {
  showCreateForm.value = true;
  newName.value = "";
  newClientType.value = "public";
  newRedirectUris.value = [""];
  createError.value = null;
}

function cancelCreate(): void {
  showCreateForm.value = false;
  createError.value = null;
}

async function submitCreate(): Promise<void> {
  createError.value = null;
  const uris = cleanUris(newRedirectUris.value);
  if (uris.length === 0) {
    createError.value = "Add at least one redirect URI.";
    return;
  }
  creating.value = true;
  try {
    const created = await registerOAuth2App(newName.value.trim(), newClientType.value, uris);
    justRegistered.value = created;
    copiedSecret.value = false;
    copiedId.value = false;
    showCreateForm.value = false;
    await loadApps();
  } catch (err) {
    createError.value = extractError(err, "Failed to register application.");
  } finally {
    creating.value = false;
  }
}

////////////////////////////////////////////////////////////////////////
//
function startEdit(app: OAuth2Application): void {
  editingId.value = app.client_id;
  editName.value = app.name;
  // Copy so edits don't mutate the displayed row until saved.
  editRedirectUris.value = app.redirect_uris.length ? [...app.redirect_uris] : [""];
  editError.value = null;
}

function cancelEdit(): void {
  editingId.value = null;
  editError.value = null;
}

async function submitEdit(clientId: string): Promise<void> {
  editError.value = null;
  const uris = cleanUris(editRedirectUris.value);
  if (uris.length === 0) {
    editError.value = "Add at least one redirect URI.";
    return;
  }
  savingEdit.value = true;
  try {
    const updated = await updateOAuth2App(clientId, {
      name: editName.value.trim(),
      redirect_uris: uris,
    });
    const idx = apps.value.findIndex((a) => a.client_id === clientId);
    if (idx !== -1) apps.value[idx] = updated;
    editingId.value = null;
  } catch (err) {
    editError.value = extractError(err, "Failed to update application.");
  } finally {
    savingEdit.value = false;
  }
}

////////////////////////////////////////////////////////////////////////
//
async function doDeregister(app: OAuth2Application): Promise<void> {
  deregisteringId.value = app.client_id;
  try {
    await deregisterOAuth2App(app.client_id);
    apps.value = apps.value.filter((a) => a.client_id !== app.client_id);
  } catch {
    loadError.value = "Failed to deregister application.";
  } finally {
    deregisteringId.value = null;
    deregisterTarget.value = null;
  }
}

////////////////////////////////////////////////////////////////////////
//
async function copyText(text: string, target: "id" | "secret"): Promise<void> {
  await navigator.clipboard.writeText(text);
  if (target === "id") {
    copiedId.value = true;
  } else {
    copiedSecret.value = true;
  }
}

////////////////////////////////////////////////////////////////////////
//
function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { dateStyle: "medium" });
}
</script>

<template>
  <AppShell>
    <div class="mx-auto max-w-lg py-4">
      <!-- Back link + header -->
      <button
        type="button"
        class="mb-3 flex items-center gap-1 text-sm text-secondary hover:text-neutral-700"
        @click="router.push('/account/settings/')"
      >
        <IconArrowLeft class="h-4 w-4" />
        Security &amp; Notifications
      </button>

      <h1 class="mb-2 text-[22px] font-medium text-neutral-900">Your applications</h1>
      <p class="mb-5 px-1 text-xs text-secondary">
        Register an OAuth2 application to grant it delegated access to your accounts without sharing
        your password — for MCP clients, importers, and other integrations you build. New apps are
        private to you and start in the testing stage; staff promote apps to all users.
        <a href="/docs/authentication.md" class="text-ocean-600 hover:underline" target="_blank"
          >Learn more</a
        >.
      </p>

      <!-- Error banner -->
      <div
        v-if="loadError"
        class="mb-3 rounded-subcard bg-coral-50 px-4 py-3 text-sm text-coral-600"
        role="alert"
      >
        {{ loadError }}
      </div>

      <!-- One-time registration result -->
      <div
        v-if="justRegistered"
        class="mb-4 rounded-card border border-mint-200 bg-mint-50 px-4 py-4"
        role="alert"
      >
        <p class="text-sm font-medium text-mint-700">"{{ justRegistered.name }}" registered.</p>

        <!-- Client ID (always available, shown here for convenience) -->
        <p class="mt-3 text-xs font-medium text-neutral-700">Client ID</p>
        <div class="mt-1 flex items-center gap-2">
          <code
            class="flex-1 overflow-x-auto rounded-subcard border border-mint-200 bg-white px-3 py-2 text-xs text-neutral-900"
            >{{ justRegistered.client_id }}</code
          >
          <button
            type="button"
            class="flex-none rounded-subcard border border-mint-300 px-3 py-2 text-xs font-medium text-mint-700 hover:bg-mint-100"
            @click="copyText(justRegistered.client_id, 'id')"
          >
            {{ copiedId ? "Copied!" : "Copy" }}
          </button>
        </div>

        <!-- Client secret — confidential clients only, shown exactly once -->
        <template v-if="justRegistered.client_secret">
          <p class="mt-3 text-xs font-medium text-neutral-700">
            Client secret — copy it now, it won't be shown again.
          </p>
          <div class="mt-1 flex items-center gap-2">
            <code
              class="flex-1 overflow-x-auto rounded-subcard border border-mint-200 bg-white px-3 py-2 text-xs text-neutral-900"
              >{{ justRegistered.client_secret }}</code
            >
            <button
              type="button"
              class="flex-none rounded-subcard border border-mint-300 px-3 py-2 text-xs font-medium text-mint-700 hover:bg-mint-100"
              @click="copyText(justRegistered.client_secret ?? '', 'secret')"
            >
              {{ copiedSecret ? "Copied!" : "Copy" }}
            </button>
          </div>
        </template>
        <p v-else class="mt-3 text-xs text-neutral-600">
          This is a public client — it has no secret and authenticates with PKCE.
        </p>

        <button
          type="button"
          class="mt-3 text-xs font-medium text-neutral-600 hover:text-neutral-800"
          @click="justRegistered = null"
        >
          Done
        </button>
      </div>

      <!-- Register button / form -->
      <div v-if="!showCreateForm" class="mb-6">
        <button
          type="button"
          class="flex items-center gap-2 rounded-subcard bg-ocean-400 px-4 py-2.5 text-sm font-medium text-white hover:bg-ocean-600"
          @click="openCreateForm"
        >
          <IconPlus class="h-4 w-4" />
          Register an application
        </button>
      </div>

      <div v-else class="mb-6 rounded-card border border-neutral-200 bg-white px-4 py-4">
        <h2 class="mb-3 text-sm font-medium text-neutral-900">Register an application</h2>
        <form class="space-y-4" @submit.prevent="submitCreate">
          <!-- Name -->
          <div>
            <label class="mb-1.5 block text-sm font-medium text-neutral-700" for="app-name">
              Name
            </label>
            <input
              id="app-name"
              v-model="newName"
              type="text"
              required
              placeholder="e.g. My budgeting MCP server"
              class="w-full rounded-subcard border border-neutral-200 px-3 py-2.5 text-sm text-neutral-900 focus:border-ocean-400 focus:outline-none focus:ring-1 focus:ring-ocean-400"
            />
          </div>

          <!-- Client type -->
          <fieldset>
            <legend class="mb-1.5 block text-sm font-medium text-neutral-700">Client type</legend>
            <div class="space-y-2">
              <label class="flex cursor-pointer items-start gap-2.5">
                <input
                  v-model="newClientType"
                  type="radio"
                  value="public"
                  class="mt-0.5 accent-ocean-400"
                />
                <span class="text-sm">
                  <span class="font-medium text-neutral-900">Public</span>
                  <span class="block text-xs text-secondary">
                    Native, mobile, desktop or MCP clients that can't keep a secret. Uses PKCE.
                  </span>
                </span>
              </label>
              <label class="flex cursor-pointer items-start gap-2.5">
                <input
                  v-model="newClientType"
                  type="radio"
                  value="confidential"
                  class="mt-0.5 accent-ocean-400"
                />
                <span class="text-sm">
                  <span class="font-medium text-neutral-900">Confidential</span>
                  <span class="block text-xs text-secondary">
                    Server-side apps that can store a secret securely. The secret is shown once, at
                    registration.
                  </span>
                </span>
              </label>
            </div>
            <p class="mt-1.5 text-xs text-secondary">
              This can't be changed later — register a new app to switch.
            </p>
          </fieldset>

          <!-- Redirect URIs -->
          <div>
            <label class="mb-1.5 block text-sm font-medium text-neutral-700">Redirect URIs</label>
            <p class="mb-2 text-xs text-secondary">
              Where the user is sent back after authorizing. Must be https, or http on the loopback
              interface (127.0.0.1 / [::1]) for native apps.
            </p>
            <div class="space-y-2">
              <div v-for="(_, idx) in newRedirectUris" :key="idx" class="flex items-center gap-2">
                <input
                  v-model="newRedirectUris[idx]"
                  type="text"
                  inputmode="url"
                  placeholder="https://app.example.com/callback"
                  class="w-full rounded-subcard border border-neutral-200 px-3 py-2.5 text-sm text-neutral-900 focus:border-ocean-400 focus:outline-none focus:ring-1 focus:ring-ocean-400"
                />
                <button
                  v-if="newRedirectUris.length > 1"
                  type="button"
                  class="flex-none rounded-subcard p-2 text-neutral-400 hover:bg-neutral-50 hover:text-coral-600"
                  aria-label="Remove redirect URI"
                  @click="removeUri(newRedirectUris, idx)"
                >
                  <IconTrash class="h-4 w-4" />
                </button>
              </div>
            </div>
            <button
              type="button"
              class="mt-2 text-xs font-medium text-ocean-600 hover:text-ocean-700"
              @click="addUri(newRedirectUris)"
            >
              + Add another URI
            </button>
          </div>

          <p v-if="createError" class="text-xs text-coral-600">{{ createError }}</p>

          <div class="flex gap-3 pt-1">
            <button
              type="submit"
              :disabled="creating || !newName.trim()"
              class="flex-1 rounded-subcard bg-ocean-400 py-2.5 text-sm font-medium text-white hover:bg-ocean-600 disabled:opacity-50"
            >
              {{ creating ? "Registering…" : "Register" }}
            </button>
            <button
              type="button"
              class="flex-1 rounded-subcard border border-neutral-200 py-2.5 text-sm font-medium text-neutral-700 hover:bg-neutral-50"
              @click="cancelCreate"
            >
              Cancel
            </button>
          </div>
        </form>
      </div>

      <!-- Existing apps -->
      <div v-if="loading" class="px-4 py-6 text-center text-sm text-secondary">Loading…</div>

      <EmptyState
        v-else-if="apps.length === 0"
        title="No applications yet"
        message="Register an application to grant an integration delegated access to your accounts."
      />

      <ul v-else class="space-y-3">
        <li
          v-for="app in apps"
          :key="app.client_id"
          class="rounded-card border border-neutral-200 bg-white px-4 py-4"
        >
          <!-- Read mode -->
          <template v-if="editingId !== app.client_id">
            <div class="flex items-start justify-between gap-3">
              <div class="min-w-0">
                <p class="text-sm font-medium text-neutral-900">{{ app.name }}</p>
                <div class="mt-1 flex flex-wrap items-center gap-1.5">
                  <span
                    class="rounded-full bg-neutral-100 px-2 py-0.5 text-[11px] font-medium text-neutral-600"
                  >
                    {{ CLIENT_TYPE_LABELS[app.client_type] }}
                  </span>
                  <span
                    class="rounded-full px-2 py-0.5 text-[11px] font-medium"
                    :class="
                      app.visibility === 'global'
                        ? 'bg-ocean-50 text-ocean-600'
                        : 'bg-neutral-100 text-neutral-600'
                    "
                  >
                    {{ VISIBILITY_LABELS[app.visibility] }}
                  </span>
                  <span
                    class="rounded-full px-2 py-0.5 text-[11px] font-medium"
                    :class="
                      app.status === 'published'
                        ? 'bg-mint-50 text-mint-600'
                        : 'bg-neutral-100 text-neutral-600'
                    "
                  >
                    {{ STATUS_LABELS[app.status] }}
                  </span>
                </div>
              </div>
              <div class="flex flex-none gap-3">
                <button
                  type="button"
                  class="text-xs font-medium text-ocean-600 hover:text-ocean-700"
                  @click="startEdit(app)"
                >
                  Edit
                </button>
                <button
                  type="button"
                  :disabled="deregisteringId === app.client_id"
                  class="text-xs font-medium text-coral-600 hover:text-coral-700 disabled:opacity-50"
                  @click="deregisterTarget = app"
                >
                  {{ deregisteringId === app.client_id ? "Removing…" : "Deregister" }}
                </button>
              </div>
            </div>

            <dl class="mt-3 space-y-1.5 text-xs">
              <div>
                <dt class="text-secondary">Client ID</dt>
                <dd class="mt-0.5 break-all font-mono text-neutral-700">{{ app.client_id }}</dd>
              </div>
              <div>
                <dt class="text-secondary">Redirect URIs</dt>
                <dd class="mt-0.5 space-y-0.5">
                  <p
                    v-for="uri in app.redirect_uris"
                    :key="uri"
                    class="break-all font-mono text-neutral-700"
                  >
                    {{ uri }}
                  </p>
                </dd>
              </div>
            </dl>
            <p class="mt-2 text-xs text-secondary">Registered {{ formatDate(app.created) }}</p>
          </template>

          <!-- Edit mode -->
          <form v-else class="space-y-4" @submit.prevent="submitEdit(app.client_id)">
            <div>
              <label
                class="mb-1.5 block text-sm font-medium text-neutral-700"
                :for="`edit-name-${app.client_id}`"
              >
                Name
              </label>
              <input
                :id="`edit-name-${app.client_id}`"
                v-model="editName"
                type="text"
                required
                class="w-full rounded-subcard border border-neutral-200 px-3 py-2.5 text-sm text-neutral-900 focus:border-ocean-400 focus:outline-none focus:ring-1 focus:ring-ocean-400"
              />
            </div>

            <div>
              <label class="mb-1.5 block text-sm font-medium text-neutral-700">Redirect URIs</label>
              <div class="space-y-2">
                <div
                  v-for="(_, idx) in editRedirectUris"
                  :key="idx"
                  class="flex items-center gap-2"
                >
                  <input
                    v-model="editRedirectUris[idx]"
                    type="text"
                    inputmode="url"
                    placeholder="https://app.example.com/callback"
                    class="w-full rounded-subcard border border-neutral-200 px-3 py-2.5 text-sm text-neutral-900 focus:border-ocean-400 focus:outline-none focus:ring-1 focus:ring-ocean-400"
                  />
                  <button
                    v-if="editRedirectUris.length > 1"
                    type="button"
                    class="flex-none rounded-subcard p-2 text-neutral-400 hover:bg-neutral-50 hover:text-coral-600"
                    aria-label="Remove redirect URI"
                    @click="removeUri(editRedirectUris, idx)"
                  >
                    <IconTrash class="h-4 w-4" />
                  </button>
                </div>
              </div>
              <button
                type="button"
                class="mt-2 text-xs font-medium text-ocean-600 hover:text-ocean-700"
                @click="addUri(editRedirectUris)"
              >
                + Add another URI
              </button>
            </div>

            <p v-if="editError" class="text-xs text-coral-600">{{ editError }}</p>

            <div class="flex gap-3">
              <button
                type="submit"
                :disabled="savingEdit || !editName.trim()"
                class="flex-1 rounded-subcard bg-ocean-400 py-2.5 text-sm font-medium text-white hover:bg-ocean-600 disabled:opacity-50"
              >
                {{ savingEdit ? "Saving…" : "Save changes" }}
              </button>
              <button
                type="button"
                class="flex-1 rounded-subcard border border-neutral-200 py-2.5 text-sm font-medium text-neutral-700 hover:bg-neutral-50"
                @click="cancelEdit"
              >
                Cancel
              </button>
            </div>
          </form>
        </li>
      </ul>

      <ConfirmSheet
        :open="deregisterTarget !== null"
        title="Deregister this application?"
        :message="`Every grant and token issued for '${deregisterTarget?.name}' is deleted, so anyone who authorized it loses access immediately. This cannot be undone.`"
        confirm-label="Deregister"
        tone="coral"
        @cancel="deregisterTarget = null"
        @confirm="deregisterTarget && doDeregister(deregisterTarget)"
      />
    </div>
  </AppShell>
</template>
