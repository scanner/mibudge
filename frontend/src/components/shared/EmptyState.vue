<script setup lang="ts">
//
// EmptyState — shown when a list has no results.  Title + message +
// optional action; the icon is provided via the default slot so the
// parent can pass any @tabler/icons-vue component.
//

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
    <div class="mb-3 text-neutral-400">
      <slot />
    </div>
    <h2 class="text-base font-medium text-neutral-700">{{ title }}</h2>
    <p v-if="message" class="mt-1 max-w-xs text-sm text-neutral-500">
      {{ message }}
    </p>
    <button
      v-if="actionLabel"
      type="button"
      class="mt-4 rounded-full bg-ocean-400 px-4 py-2 text-sm font-medium text-white hover:bg-ocean-600"
      @click="$emit('action')"
    >
      {{ actionLabel }}
    </button>
  </div>
</template>
