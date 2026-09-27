<script setup lang="ts">
//
// BaseSheet -- the one shell for sheets and dialogs.  Presentational
// (base); emits `close`.
//
// Below `md` it is a bottom sheet; from `md` it is a centred card
// `w-sheet` wide (`align="top"` places it near the top instead, for a
// menu-like sheet).  It teleports to `body`, fades in over the scrim,
// and calls `useModal` for the scroll lock, Escape and focus return;
// clicking the scrim emits `close`.  `fullscreen` instead slides a
// full-page sheet up over the canvas.
//
// `title` renders the heading the dialog is labelled by; without one,
// pass `label` for the dialog's accessible name.  Slots: the default
// slot is the scrolling body, `header-actions` sits at the heading's
// trailing edge, and `footer` stays pinned below the body, divided from
// it by rules.  `layer="dialog"` stacks it above an open sheet.
//

// 3rd party imports
//
import { computed, useId, useSlots } from "vue";

// app imports
//
import { useModal } from "@/composables/useModal";

////////////////////////////////////////////////////////////////////////
//
interface Props {
  open: boolean;
  title?: string;
  label?: string;
  layer?: "sheet" | "dialog";
  align?: "center" | "top";
  fullscreen?: boolean;
}

const props = withDefaults(defineProps<Props>(), {
  title: undefined,
  label: undefined,
  layer: "sheet",
  align: "center",
  fullscreen: false,
});

const emit = defineEmits<{ (e: "close"): void }>();

useModal(
  () => props.open,
  () => emit("close"),
);

const slots = useSlots();
const titleId = useId();

const layerClass = computed(() =>
  props.layer === "dialog" ? "z-dialog" : "z-sheet",
);
const divided = computed(() => !!slots.footer);
</script>

<template>
  <Teleport to="body">
    <Transition v-if="fullscreen" name="slide-up">
      <div
        v-if="open"
        :class="['fixed inset-0 overflow-y-auto bg-canvas', layerClass]"
        role="dialog"
        aria-modal="true"
        :aria-labelledby="title ? titleId : undefined"
        :aria-label="title ? undefined : label"
      >
        <div class="mx-auto max-w-lg px-page-x pb-8 pt-4">
          <div
            v-if="title || $slots['header-actions']"
            class="mb-4 flex items-center justify-between gap-3"
          >
            <h2 v-if="title" :id="titleId" class="text-title text-fg">
              {{ title }}
            </h2>
            <slot name="header-actions" />
          </div>
          <slot />
        </div>
      </div>
    </Transition>

    <Transition v-else name="fade">
      <div
        v-if="open"
        :class="[
          'fixed inset-0 flex items-end justify-center',
          align === 'top' ? 'md:items-start md:pt-20' : 'md:items-center',
          layerClass,
        ]"
      >
        <div class="absolute inset-0 bg-scrim/40" @click="emit('close')" />
        <div
          class="relative flex max-h-sheet w-full flex-col rounded-t-card bg-surface shadow-overlay md:w-sheet md:rounded-card"
          role="dialog"
          aria-modal="true"
          :aria-labelledby="title ? titleId : undefined"
          :aria-label="title ? undefined : label"
        >
          <div
            v-if="title || $slots['header-actions']"
            :class="[
              'flex items-center justify-between gap-3 px-5 pt-5',
              divided ? 'border-b border-border pb-3' : '',
            ]"
          >
            <h2 v-if="title" :id="titleId" class="text-title text-fg">
              {{ title }}
            </h2>
            <slot name="header-actions" />
          </div>
          <div
            :class="[
              'min-h-0 flex-1 overflow-y-auto px-5',
              divided ? 'py-4' : title ? 'pb-5 pt-4' : 'py-5',
            ]"
          >
            <slot />
          </div>
          <div v-if="divided" class="border-t border-border px-5 py-4">
            <slot name="footer" />
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>
