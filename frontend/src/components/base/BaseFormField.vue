<script setup lang="ts">
//
// BaseFormField -- a label, a control, an optional hint and an optional
// error, wired together.  Presentational (base).
//
// The control goes in the default slot, which receives `{ id,
// describedBy, invalid }` to bind onto it:
//
//   <BaseFormField label="Name" :error="errors.name">
//     <template #default="{ id, describedBy, invalid }">
//       <BaseInput :id="id" v-model="name"
//         :aria-describedby="describedBy" :invalid="invalid" />
//     </template>
//   </BaseFormField>
//
// The label points at `id` (generated unless given); the hint (below
// the control) and the error get ids that `describedBy` lists.  The
// error has `role="alert"` so a screen reader announces it when it
// appears.  `optional` adds "(optional)" to the label.
//

// 3rd party imports
//
import { computed, useId } from "vue";

////////////////////////////////////////////////////////////////////////
//
interface Props {
  label: string;
  id?: string;
  hint?: string;
  error?: string | null;
  optional?: boolean;
}

const props = withDefaults(defineProps<Props>(), {
  id: undefined,
  hint: undefined,
  error: null,
  optional: false,
});

const generated = useId();
const fieldId = computed(() => props.id ?? generated);
const hintId = computed(() => `${fieldId.value}-hint`);
const errorId = computed(() => `${fieldId.value}-error`);

const describedBy = computed(() => {
  const ids = [];
  if (props.hint) ids.push(hintId.value);
  if (props.error) ids.push(errorId.value);
  return ids.length ? ids.join(" ") : undefined;
});
</script>

<template>
  <div>
    <label :for="fieldId" class="mb-1.5 block text-label text-fg">
      {{ label }}
      <span v-if="optional" class="font-normal text-fg-subtle">(optional)</span>
    </label>
    <slot v-bind="{ id: fieldId, describedBy, invalid: !!error }" />
    <p v-if="hint" :id="hintId" class="mt-1.5 text-meta text-fg-muted">
      {{ hint }}
    </p>
    <p
      v-if="error"
      :id="errorId"
      class="mt-1 text-meta text-danger-fg"
      role="alert"
    >
      {{ error }}
    </p>
  </div>
</template>
