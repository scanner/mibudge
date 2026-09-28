<script setup lang="ts">
//
// ConfirmSheet -- the confirmation step before a destructive or
// significant action.  Presentational: emits `confirm` or `cancel`.
//
// A dialog-layer BaseSheet (so it opens above another sheet) holding
// the title, an optional message and the two buttons.  `tone` sets the
// confirm button: `danger` (the default, for destructive actions) or
// `primary`.
//

// app imports
//
import BaseButton from "@/components/base/BaseButton.vue";
import BaseSheet from "@/components/base/BaseSheet.vue";

////////////////////////////////////////////////////////////////////////
//
interface Props {
  open: boolean;
  title: string;
  message?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: "danger" | "primary";
}

withDefaults(defineProps<Props>(), {
  message: undefined,
  confirmLabel: "Delete",
  cancelLabel: "Cancel",
  tone: "danger",
});

const emit = defineEmits<{
  (event: "confirm"): void;
  (event: "cancel"): void;
}>();
</script>

<template>
  <BaseSheet :open="open" :title="title" layer="dialog" @close="emit('cancel')">
    <p v-if="message" class="text-body-sm text-fg-muted">
      {{ message }}
    </p>
    <div class="mt-5 flex justify-end gap-2">
      <BaseButton variant="secondary" @click="emit('cancel')">
        {{ cancelLabel }}
      </BaseButton>
      <BaseButton
        :variant="tone === 'danger' ? 'danger' : 'primary'"
        @click="emit('confirm')"
      >
        {{ confirmLabel }}
      </BaseButton>
    </div>
  </BaseSheet>
</template>
