<script setup lang="ts">
//
// EmptyState — shown when a list has no results.  Title + message +
// optional action; the icon is provided via the default slot so the
// parent can pass any @tabler/icons-vue component.
//

// app imports
//
import BaseButton from "@/components/base/BaseButton.vue";

////////////////////////////////////////////////////////////////////////
//
interface Props {
  title: string;
  message?: string;
  actionLabel?: string;
}

defineProps<Props>();

defineEmits<{
  (event: "action"): void;
}>();
</script>

<template>
  <div class="flex flex-col items-center justify-center px-6 py-12 text-center">
    <div class="mb-3 text-icon-muted">
      <slot />
    </div>
    <h2 class="text-item-title text-fg">{{ title }}</h2>
    <p v-if="message" class="mt-1 max-w-xs text-body-sm text-fg-muted">
      {{ message }}
    </p>
    <BaseButton v-if="actionLabel" class="mt-4" @click="$emit('action')">
      {{ actionLabel }}
    </BaseButton>
  </div>
</template>
