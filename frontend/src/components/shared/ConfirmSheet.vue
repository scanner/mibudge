<script setup lang="ts">
//
// ConfirmSheet — bottom sheet for destructive confirmations.
//
// Rendered via <Teleport to="body"> so backdrop clicks don't fight
// ancestor scroll/overflow rules.  On mobile it slides up from the
// bottom; on ≥md it centres as a modal.  `useModal` provides the
// scroll lock, Escape-to-cancel and focus return.
//

// app imports
//
import { useModal } from "@/composables/useModal";

////////////////////////////////////////////////////////////////////////
//
interface Props {
  open: boolean;
  title: string;
  message?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  // Tone for the confirm button.  Default coral (destructive).
  tone?: "coral" | "ocean";
}

const props = withDefaults(defineProps<Props>(), {
  confirmLabel: "Delete",
  cancelLabel: "Cancel",
  tone: "coral",
});

const emit = defineEmits<{
  (event: "confirm"): void;
  (event: "cancel"): void;
}>();

////////////////////////////////////////////////////////////////////////
//
useModal(
  () => props.open,
  () => emit("cancel"),
);
</script>

<template>
  <Teleport to="body">
    <Transition name="fade">
      <div
        v-if="open"
        class="fixed inset-0 z-dialog flex items-end justify-center md:items-center"
      >
        <div class="absolute inset-0 bg-scrim/40" @click="emit('cancel')" />
        <div
          class="relative w-full rounded-t-card bg-surface p-5 shadow-overlay md:w-sheet md:rounded-card"
          role="dialog"
          aria-modal="true"
        >
          <h2 class="text-title text-fg">{{ title }}</h2>
          <p v-if="message" class="mt-2 text-body-sm text-fg-muted">
            {{ message }}
          </p>
          <div class="mt-5 flex justify-end gap-2">
            <button
              type="button"
              class="rounded-pill px-4 py-2 text-label text-fg hover:bg-surface-muted"
              @click="emit('cancel')"
            >
              {{ cancelLabel }}
            </button>
            <button
              type="button"
              class="rounded-pill px-4 py-2 text-label text-fg-on-accent"
              :class="
                tone === 'coral'
                  ? 'bg-danger-solid hover:bg-danger-solid-hover'
                  : 'bg-accent hover:bg-accent-hover'
              "
              @click="emit('confirm')"
            >
              {{ confirmLabel }}
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 120ms ease-out;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
