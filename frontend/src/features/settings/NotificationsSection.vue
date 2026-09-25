<script setup lang="ts">
//
// NotificationsSection — email digest frequency and per-kind delivery
// modes.  Feature component (settings); state and requests live in
// `useNotificationPrefs`.
//

// app imports
//
import type { DeliveryMode } from "@/models/notification";
import { useSessionStore } from "@/stores/session";
import {
  DELIVERY_MODE_OPTIONS,
  DIGEST_OPTIONS,
  useNotificationPrefs,
} from "./useNotificationPrefs";

////////////////////////////////////////////////////////////////////////
//
const session = useSessionStore();
const { prefs, emailDigestFrequency, loading, error, setDeliveryMode, saveEmailDigest } =
  useNotificationPrefs();
</script>

<template>
  <!-- ── Notifications ────────────────────────────────────────── -->
  <h1 class="mb-5 mt-10 text-[22px] font-medium text-neutral-900">Notifications</h1>

  <section>
    <!-- Error banner -->
    <div
      v-if="error"
      class="mb-3 rounded-subcard bg-coral-50 px-4 py-3 text-sm text-coral-600"
      role="alert"
    >
      {{ error }}
    </div>

    <div class="rounded-card border border-neutral-200 bg-white">
      <!-- Loading skeleton -->
      <div v-if="loading" class="px-4 py-6 text-center text-sm text-secondary">Loading…</div>

      <template v-else>
        <!-- Notification destination (email only for now) -->
        <div class="border-b border-neutral-100 px-4 py-3">
          <p class="text-xs text-secondary">Notifications are sent to</p>
          <p class="mt-0.5 text-sm font-medium text-neutral-900">
            {{ session.user?.email }}
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
          v-for="pref in prefs"
          :key="pref.kind"
          class="flex items-center justify-between border-b border-neutral-100 px-4 py-3 last:border-b-0"
        >
          <span class="text-sm text-neutral-700">{{ pref.displayName }}</span>

          <!-- Suppressible: 3-way delivery mode selector -->
          <select
            v-if="pref.canSuppress"
            :value="pref.deliveryMode"
            class="rounded-subcard border border-neutral-200 bg-white py-1.5 pl-2.5 pr-7 text-sm text-neutral-900 focus:border-ocean-400 focus:outline-none focus:ring-1 focus:ring-ocean-400"
            @change="
              setDeliveryMode(pref, ($event.target as HTMLSelectElement).value as DeliveryMode)
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
</template>
