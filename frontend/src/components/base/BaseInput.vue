<script setup lang="ts">
//
// BaseInput -- a single-line text field.  Presentational (base).
//
// Every attribute and listener (`id`, `type`, `placeholder`,
// `autocomplete`, `@blur`, `class`, ...) lands on the native `<input>`.
// `v-model` binds its value.  `invalid` draws the danger border and
// sets `aria-invalid`.  `mono` sets the text in Plex Mono (amounts,
// account numbers).  `size="sm"` is the compact field used inside
// dense rows.  `focus()` is exposed for callers that focus by ref.
//

// 3rd party imports
//
import { computed, ref } from "vue";

////////////////////////////////////////////////////////////////////////
//
defineOptions({ inheritAttrs: false });

interface Props {
  invalid?: boolean;
  mono?: boolean;
  size?: "sm" | "md";
  inline?: boolean;
}

const props = withDefaults(defineProps<Props>(), {
  invalid: false,
  mono: false,
  size: "md",
  inline: false,
});

const model = defineModel<string | number | null>();
const el = ref<HTMLInputElement | null>(null);

defineExpose({ focus: () => el.value?.focus() });

const classes = computed(() => fieldClasses(props));
</script>

<script lang="ts">
////////////////////////////////////////////////////////////////////////
//
// Shared by BaseInput, BaseSelect and BaseTextarea so every field has
// one border, focus ring and invalid state.
//
export function fieldClasses(p: {
  invalid?: boolean;
  mono?: boolean;
  size?: "sm" | "md";
  inline?: boolean;
}): string[] {
  return [
    p.inline ? "" : "block w-full",
    "rounded-control border bg-surface text-input text-fg placeholder-fg-subtle transition-colors focus:outline-none focus:ring-1",
    p.invalid
      ? "border-danger-solid focus:border-danger-solid focus:ring-danger-solid"
      : "border-border-strong focus:border-border-focus focus:ring-border-focus",
    p.size === "sm" ? "px-3 py-1.5" : "px-3 py-2.5",
    p.mono ? "font-mono" : "",
  ];
}
</script>

<template>
  <input
    ref="el"
    v-model="model"
    v-bind="$attrs"
    :aria-invalid="invalid || undefined"
    :class="classes"
  />
</template>
