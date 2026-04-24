<script setup lang="ts">
//
// ProgressBar — horizontal progress indicator used on budget cards,
// detail heroes, and fill-up bands.  Fill colour follows the rules in
// UI_SPEC.md §2.4 and can be overridden via the `tone` prop.
//

// 3rd party imports
//
import { computed } from "vue";

////////////////////////////////////////////////////////////////////////
//
export type ProgressTone = "mint" | "ocean" | "amber" | "coral" | "neutral";

interface Props {
  value: number; // 0..100
  tone?: ProgressTone;
  // Heights from UI_SPEC: 5px (card), 8px (detail hero), 3px (fill-up).
  height?: 3 | 5 | 8;
}

const props = withDefaults(defineProps<Props>(), {
  tone: "ocean",
  height: 5,
});

////////////////////////////////////////////////////////////////////////
//
const clamped = computed(() => Math.max(0, Math.min(100, props.value)));

const toneClass = computed(() => {
  switch (props.tone) {
    case "mint":
      return "bg-mint-400";
    case "ocean":
      return "bg-ocean-400";
    case "amber":
      return "bg-amber-400";
    case "coral":
      return "bg-coral-400";
    case "neutral":
      return "bg-neutral-400";
  }
});

const heightClass = computed(() => {
  switch (props.height) {
    case 3:
      return "h-[3px]";
    case 5:
      return "h-[5px]";
    case 8:
      return "h-[8px]";
  }
});
</script>

<template>
  <div
    class="w-full overflow-hidden rounded-full bg-neutral-100"
    :class="heightClass"
    role="progressbar"
    :aria-valuenow="clamped"
    aria-valuemin="0"
    aria-valuemax="100"
  >
    <div
      class="h-full rounded-full transition-[width]"
      :class="toneClass"
      :style="{ width: `${clamped}%` }"
    />
  </div>
</template>
