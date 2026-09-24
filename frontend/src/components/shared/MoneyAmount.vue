<script setup lang="ts">
//
// MoneyAmount — the canonical way to render a monetary value.
//
// Always IBM Plex Mono.  Formatting goes through `formatMoney` in
// `domain/money`, the SPA's single currency formatter.  `amount` is a
// `Money`, or an API decimal string paired with `currency`.
//
// The `aria-label` carries the unformatted decimal so screen readers
// hear "142 dollars and 80 cents" instead of glyph-by-glyph.
//

// 3rd party imports
//
import { computed } from "vue";

// app imports
//
import { formatMoney, Money } from "@/domain/money";

////////////////////////////////////////////////////////////////////////
//
interface Props {
  amount: Money | string;
  currency?: string;
  size?: "sm" | "md" | "lg" | "hero";
  showSign?: boolean;
  coloured?: boolean;
}

const props = withDefaults(defineProps<Props>(), {
  currency: undefined,
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
const money = computed(() =>
  props.amount instanceof Money ? props.amount : Money.of(props.amount, props.currency),
);

////////////////////////////////////////////////////////////////////////
//
const colourClass = computed(() => {
  if (!props.coloured) return "";
  if (money.value.isNegative()) return "text-coral-600";
  if (money.value.isPositive()) return "text-mint-600";
  return "";
});

////////////////////////////////////////////////////////////////////////
//
const formatted = computed(() =>
  formatMoney(money.value, { signDisplay: props.showSign ? "always" : "auto" }),
);

////////////////////////////////////////////////////////////////////////
//
// Screen-reader label: "142.80 USD".  Intl produces locale-formatted
// text that can be ambiguous to assistive tech; the raw decimal is
// clearer.
//
const ariaLabel = computed(() => `${money.value.toDecimalString()} ${money.value.currency}`);
</script>

<template>
  <span class="font-mono tabular-nums" :class="[sizeClass, colourClass]" :aria-label="ariaLabel">
    {{ formatted }}
  </span>
</template>
