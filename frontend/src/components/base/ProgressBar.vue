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

const TONES: Record<ProgressTone, string> = {
  funded: "bg-progress-funded",
  active: "bg-progress-active",
  behind: "bg-progress-behind",
  over: "bg-progress-over",
  paused: "bg-progress-paused",
};

const HEIGHTS: Record<NonNullable<Props["size"]>, string> = {
  sm: "h-progress-sm",
  md: "h-progress-md",
  lg: "h-progress-lg",
};

const toneClass = computed(() => TONES[props.tone]);
const heightClass = computed(() => HEIGHTS[props.size]);
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
