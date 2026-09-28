<script setup lang="ts">
//
// BaseTextarea -- a multi-line text field, styled like BaseInput.
// Presentational (base).
//
// Every attribute and listener (`rows`, `placeholder`, `@input`, ...)
// lands on the native `<textarea>`; `v-model` binds its value.
// `invalid` and `inline` work as on BaseInput.  It does not resize by drag.
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
}

const props = withDefaults(defineProps<Props>(), {
  invalid: false,
  inline: false,
});

const model = defineModel<string | null>();
const el = ref<HTMLTextAreaElement | null>(null);

defineExpose({ focus: () => el.value?.focus() });

const classes = computed(() => [...fieldClasses(props), "resize-none"]);
</script>

<template>
  <textarea
    ref="el"
    v-model="model"
    v-bind="$attrs"
    :aria-invalid="invalid || undefined"
    :class="classes"
  />
</template>
