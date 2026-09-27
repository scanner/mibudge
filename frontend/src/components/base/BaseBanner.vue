<script setup lang="ts">
//
// BaseBanner -- an inline message box: an error, a confirmation, a
// notice.  Presentational (base).
//
// `tone` (`danger`, `success`, `info`, `warning`) picks the status
// colours: the tinted background, the text and a light border.  A
// `danger` banner has `role="alert"` so a screen reader announces it;
// the others have `role="status"`.  The message goes in the default
// slot.
//

// 3rd party imports
//
import { computed } from "vue";

////////////////////////////////////////////////////////////////////////
//
export type BannerTone = "danger" | "success" | "info" | "warning";

interface Props {
  tone?: BannerTone;
}

const props = withDefaults(defineProps<Props>(), { tone: "info" });

const TONES: Record<BannerTone, string> = {
  danger: "border-danger-border bg-danger-bg text-danger-fg",
  success: "border-success-border bg-success-bg text-success-fg",
  info: "border-info-border bg-info-bg text-info-fg",
  warning: "border-warning-border bg-warning-bg text-warning-fg",
};

const classes = computed(() => [
  "rounded-control border px-card-x py-card-y text-body-sm",
  TONES[props.tone],
]);
</script>

<template>
  <div :role="tone === 'danger' ? 'alert' : 'status'" :class="classes">
    <slot />
  </div>
</template>
