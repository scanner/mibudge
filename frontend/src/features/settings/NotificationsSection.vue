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
import BaseSelect from "@/components/base/BaseSelect.vue";
import BasePageHeader from "@/components/base/BasePageHeader.vue";
import BaseCard from "@/components/base/BaseCard.vue";
import BaseListRow from "@/components/base/BaseListRow.vue";
import BaseCardSection from "@/components/base/BaseCardSection.vue";
import BaseBanner from "@/components/base/BaseBanner.vue";

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
  <BasePageHeader title="Notifications" class="mt-10" />

  <section>
    <!-- Error banner -->
    <BaseBanner v-if="error" tone="danger" class="mb-3">
      {{ error }}
    </BaseBanner>

    <BaseCard>
      <!-- Loading skeleton -->
      <div
        v-if="loading"
        class="px-4 py-6 text-center text-body-sm text-fg-muted"
      >
        Loading…
      </div>

      <template v-else>
        <!-- Notification destination (email only for now) -->
        <BaseCardSection>
          <p class="text-meta text-fg-muted">Notifications are sent to</p>
          <p class="mt-0.5 text-label text-fg">
            {{ session.user?.email }}
          </p>
        </BaseCardSection>

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
          <BaseSelect
            :model-value="emailDigestFrequency"
            @update:model-value="setEmailDigest($event as DigestFrequency)"
            size="sm"
            inline
          >
            <option
              v-for="opt in DIGEST_OPTIONS"
              :key="opt.value"
              :value="opt.value"
            >
              {{ opt.label }}
            </option>
          </BaseSelect>
        </div>

        <!-- Per-kind toggles -->
        <BaseListRow
          v-for="pref in prefs"
          class="justify-between"
          :key="pref.kind"
        >
          <span class="text-body-sm text-fg">{{ pref.displayName }}</span>

          <!-- Suppressible: 3-way delivery mode selector -->
          <BaseSelect
            v-if="pref.canSuppress"
            :model-value="deliveryModeOf(pref)"
            @update:model-value="setDeliveryMode(pref, $event as DeliveryMode)"
            size="sm"
            inline
          >
            <option
              v-for="opt in DELIVERY_MODE_OPTIONS"
              :key="opt.value"
              :value="opt.value"
            >
              {{ opt.label }}
            </option>
          </BaseSelect>

          <!-- Non-suppressible: locked indicator -->
          <span v-else class="text-meta text-fg-muted">Always on</span>
        </BaseListRow>
      </template>
    </BaseCard>
  </section>
</template>
