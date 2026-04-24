<script setup lang="ts">
//
// ConfirmSheet — bottom sheet for destructive confirmations.
//
// Rendered via <Teleport to="body"> so backdrop click and Escape
// detection don't fight ancestor scroll/overflow rules.  On mobile it
// slides up from the bottom; on ≥md it centres as a modal.
//

// 3rd party imports
//
import { onBeforeUnmount, onMounted, watch } from "vue";

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
function onKey(e: KeyboardEvent) {
  if (e.key === "Escape" && props.open) emit("cancel");
}

onMounted(() => window.addEventListener("keydown", onKey));
onBeforeUnmount(() => window.removeEventListener("keydown", onKey));

// Lock body scroll while the sheet is visible.
watch(
  () => props.open,
  (isOpen) => {
    document.body.style.overflow = isOpen ? "hidden" : "";
  },
);
</script>

<template>
  <Teleport to="body">
    <Transition name="fade">
      <div v-if="open" class="fixed inset-0 z-50 flex items-end justify-center md:items-center">
        <div class="absolute inset-0 bg-neutral-900/40" @click="emit('cancel')" />
        <div
          class="relative w-full rounded-t-2xl bg-white p-5 shadow-xl md:w-[420px] md:rounded-card"
          role="dialog"
          aria-modal="true"
        >
          <h2 class="text-base font-medium text-neutral-900">{{ title }}</h2>
          <p v-if="message" class="mt-2 text-sm text-neutral-600">{{ message }}</p>
          <div class="mt-5 flex justify-end gap-2">
            <button
              type="button"
              class="rounded-full px-4 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-100"
              @click="emit('cancel')"
            >
              {{ cancelLabel }}
            </button>
            <button
              type="button"
              class="rounded-full px-4 py-2 text-sm font-medium text-white"
              :class="
                tone === 'coral'
                  ? 'bg-coral-400 hover:bg-coral-600'
                  : 'bg-ocean-400 hover:bg-ocean-600'
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
