<script setup lang="ts">
//
// BaseToggle -- an on/off switch.  Presentational (base).
//
// A visually hidden checkbox carries the state, so the caller's
// surrounding `<label>` names it and a click anywhere on that label
// flips it.  `v-model` binds the boolean; other attributes and
// listeners land on the checkbox.  The track is the accent when on and
// `border-strong` when off.
//

////////////////////////////////////////////////////////////////////////
//
defineOptions({ inheritAttrs: false });

const model = defineModel<boolean>({ default: false });
</script>

<template>
  <span class="relative inline-flex flex-none">
    <input
      v-model="model"
      v-bind="$attrs"
      type="checkbox"
      role="switch"
      class="peer sr-only"
    />
    <span
      aria-hidden="true"
      :class="[
        'h-6 w-10 rounded-pill transition-colors duration-base',
        model ? 'bg-accent' : 'bg-border-strong',
      ]"
    />
    <span
      aria-hidden="true"
      :class="[
        'absolute top-0.5 h-5 w-5 rounded-pill bg-surface shadow-control transition-transform duration-base',
        model ? 'translate-x-4' : 'translate-x-0.5',
      ]"
    />
  </span>
</template>
