<script setup lang="ts">
//
// ProgressBar -- horizontal progress indicator used on budget cards,
// detail heroes, and fill-up bands.  Presentational (base).
//
// `tone` picks the `progress-*` fill (`progressTone()` maps a budget
// status to it); `size` is `sm` (fill-up band), `md` (budget card) or
// `lg` (detail hero).
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
  size?: "sm" | "md" | "lg";
}

const props = withDefaults(defineProps<Props>(), {
  tone: "active",
  size: "md",
});

////////////////////////////////////////////////////////////////////////
//
const clamped = computed(() => Math.max(0, Math.min(100, props.value)));

const toneClass = computed(() => {
  switch (props.tone) {
    case "funded":
      return "bg-progress-funded";
    case "active":
      return "bg-progress-active";
    case "behind":
      return "bg-progress-behind";
    case "over":
      return "bg-progress-over";
    case "paused":
      return "bg-progress-paused";
  }
});

const heightClass = computed(() => {
  switch (props.size) {
    case "sm":
      return "h-progress-sm";
    case "md":
      return "h-progress-md";
    case "lg":
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
