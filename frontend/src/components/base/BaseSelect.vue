<script setup lang="ts">
//
// BaseSelect -- a native select, styled like BaseInput.  Presentational
// (base).
//
// The `<option>`s go in the default slot.  Every attribute and listener
// lands on the native `<select>`; `v-model` binds its value.  `invalid`,
// `size` and `inline` work as on BaseInput.
//

// 3rd party imports
//
import { computed, ref } from "vue";

// app imports
//
import { fieldClasses } from "./BaseInput.vue";

////////////////////////////////////////////////////////////////////////
//
defineOptions({ inheritAttrs: false });

interface Props {
  invalid?: boolean;
  inline?: boolean;
  size?: "sm" | "md";
}

const props = withDefaults(defineProps<Props>(), {
  invalid: false,
  size: "md",
  inline: false,
});

const model = defineModel<string | number | null>();
const el = ref<HTMLSelectElement | null>(null);

defineExpose({ focus: () => el.value?.focus() });

const classes = computed(() => [...fieldClasses(props), "pr-8"]);
</script>

<template>
  <select
    ref="el"
    v-model="model"
    v-bind="$attrs"
    :aria-invalid="invalid || undefined"
    :class="classes"
  >
    <slot />
  </select>
</template>
