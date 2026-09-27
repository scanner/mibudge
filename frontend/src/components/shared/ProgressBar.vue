<script setup lang="ts">
//
// ProgressBar — horizontal progress indicator used on budget cards,
// detail heroes, and fill-up bands.  Fill colour follows the rules in
// UI_SPEC.md §2.4 and can be overridden via the `tone` prop.
//

// 3rd party imports
//
import { computed } from "vue";

// app imports
//
import type { ProgressTone } from "@/domain/budgetStatus";

////////////////////////////////////////////////////////////////////////
//

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
      return "bg-progress-funded";
    case "ocean":
      return "bg-progress-active";
    case "amber":
      return "bg-progress-behind";
    case "coral":
      return "bg-progress-over";
    case "neutral":
      return "bg-progress-paused";
  }
});

const heightClass = computed(() => {
  switch (props.height) {
    case 3:
      return "h-progress-sm";
    case 5:
      return "h-progress-md";
    case 8:
      return "h-progress-lg";
  }
});
</script>

<template>
  <div
    class="w-full overflow-hidden rounded-pill bg-progress-track"
    :class="heightClass"
    role="progressbar"
    :aria-valuenow="clamped"
    aria-valuemin="0"
    aria-valuemax="100"
  >
    <div
      class="h-full rounded-pill transition-width"
      :class="toneClass"
      :style="{ width: `${clamped}%` }"
    />
  </div>
</template>
