<script setup lang="ts">
//
// MoneyAmount — the canonical way to render a monetary value.
//
// Always IBM Plex Mono, never parsed to Number for arithmetic (the
// decimal string from the API is passed straight into Intl through a
// Number only for display formatting, which is safe for typical
// account balances; for summation always use decimal.js on the string
// values and then hand the result here).
//
// The `aria-label` carries the unformatted decimal so screen readers
// hear "142 dollars and 80 cents" instead of glyph-by-glyph.
//

// 3rd party imports
//
import { computed } from "vue";

////////////////////////////////////////////////////////////////////////
//
interface Props {
  amount: string;
  currency: string;
  size?: "sm" | "md" | "lg" | "hero";
  showSign?: boolean;
  coloured?: boolean;
}

const props = withDefaults(defineProps<Props>(), {
  size: "md",
  showSign: false,
  coloured: false,
});

////////////////////////////////////////////////////////////////////////
//
const sizeClass = computed(() => {
  switch (props.size) {
    case "sm":
      return "text-xs";
    case "md":
      return "text-[15px] font-medium";
    case "lg":
      return "text-[22px] font-medium";
    case "hero":
      return "text-[36px] font-medium leading-tight";
  }
});

////////////////////////////////////////////////////////////////////////
//
const numeric = computed(() => {
  // parseFloat is fine for *display* — never use it for arithmetic.
  const n = Number.parseFloat(props.amount);
  return Number.isFinite(n) ? n : 0;
});

const isNegative = computed(() => numeric.value < 0);

////////////////////////////////////////////////////////////////////////
//
const colourClass = computed(() => {
  if (!props.coloured) return "";
  if (isNegative.value) return "text-coral-600";
  if (numeric.value > 0) return "text-mint-600";
  return "";
});

////////////////////////////////////////////////////////////////////////
//
const formatted = computed(() => {
  const formatter = new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: props.currency || "USD",
    signDisplay: props.showSign ? "always" : "auto",
  });
  return formatter.format(numeric.value);
});

////////////////////////////////////////////////////////////////////////
//
// Screen-reader label: "142.80 USD".  Intl produces locale-formatted
// text that can be ambiguous to assistive tech; the raw decimal is
// clearer.
//
const ariaLabel = computed(() => `${props.amount} ${props.currency}`);
</script>

<template>
  <span class="font-mono tabular-nums" :class="[sizeClass, colourClass]" :aria-label="ariaLabel">
    {{ formatted }}
  </span>
</template>
