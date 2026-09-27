<script setup lang="ts">
//
// NotificationsSection — email digest frequency and per-kind delivery
// modes.  Feature component (settings); state and requests live in
// `useNotificationPrefs`.
//

// app imports
//
import type { DeliveryMode, DigestFrequency } from "@/models/notification";
import { useSessionStore } from "@/stores/session";
import {
  DELIVERY_MODE_OPTIONS,
  DIGEST_OPTIONS,
  useNotificationPrefs,
} from "./useNotificationPrefs";

////////////////////////////////////////////////////////////////////////
//
const session = useSessionStore();
const {
  prefs,
  emailDigestFrequency,
  loading,
  error,
  deliveryModeOf,
  setDeliveryMode,
  setEmailDigest,
} = useNotificationPrefs();
</script>

<template>
  <!-- ── Notifications ────────────────────────────────────────── -->
  <h1 class="mb-5 mt-10 text-page-title text-fg">Notifications</h1>

  <section>
    <!-- Error banner -->
    <div
      v-if="error"
      class="mb-3 rounded-control bg-danger-bg px-4 py-3 text-body-sm text-danger-fg"
      role="alert"
    >
      {{ error }}
    </div>

    <div class="rounded-card border border-border bg-surface">
      <!-- Loading skeleton -->
      <div
        v-if="loading"
        class="px-4 py-6 text-center text-body-sm text-fg-muted"
      >
        Loading…
      </div>

      <template v-else>
        <!-- Notification destination (email only for now) -->
        <div class="border-b border-border-subtle px-4 py-3">
          <p class="text-meta text-fg-muted">Notifications are sent to</p>
          <p class="mt-0.5 text-label text-fg">
            {{ session.user?.email }}
          </p>
        </div>

        <!-- Email digest frequency (only email channel is active) -->
        <div
          class="flex items-center justify-between border-b border-border-subtle px-4 py-4"
        >
          <div>
            <p class="text-label text-fg">Email digest</p>
            <p class="mt-0.5 text-meta text-fg-muted">
              How often to receive email digests
            </p>
          </div>
          <select
            :value="emailDigestFrequency"
            class="rounded-control border border-border-strong bg-surface py-1.5 pl-2.5 pr-7 text-input text-fg focus:border-border-focus focus:outline-none focus:ring-1 focus:ring-border-focus"
            @change="
              setEmailDigest(
                ($event.target as HTMLSelectElement).value as DigestFrequency,
              )
            "
          >
            <option
              v-for="opt in DIGEST_OPTIONS"
              :key="opt.value"
              :value="opt.value"
            >
              {{ opt.label }}
            </option>
          </select>
        </div>

        <!-- Per-kind toggles -->
        <div
          v-for="pref in prefs"
          :key="pref.kind"
          class="flex items-center justify-between border-b border-border-subtle px-4 py-3 last:border-b-0"
        >
          <span class="text-body-sm text-fg">{{ pref.displayName }}</span>

          <!-- Suppressible: 3-way delivery mode selector -->
          <select
            v-if="pref.canSuppress"
            :value="deliveryModeOf(pref)"
            class="rounded-control border border-border-strong bg-surface py-1.5 pl-2.5 pr-7 text-input text-fg focus:border-border-focus focus:outline-none focus:ring-1 focus:ring-border-focus"
            @change="
              setDeliveryMode(
                pref,
                ($event.target as HTMLSelectElement).value as DeliveryMode,
              )
            "
          >
            <option
              v-for="opt in DELIVERY_MODE_OPTIONS"
              :key="opt.value"
              :value="opt.value"
            >
              {{ opt.label }}
            </option>
          </select>

          <!-- Non-suppressible: locked indicator -->
          <span v-else class="text-meta text-fg-muted">Always on</span>
        </div>
      </template>
    </div>
  </section>
</template>
