<script setup lang="ts">
//
// PasswordStrengthMeter — renders a 5-bar zxcvbn strength indicator.
//
// zxcvbn is loaded lazily on first evaluation (~800 KB); subsequent calls
// reuse the cached module.  Evaluation is debounced 200ms to avoid
// blocking on every keystroke.
//
// Emits `score` so the parent can gate form submission on score >= 2.
//

// 3rd party imports
//
import { ref, watch } from "vue";

////////////////////////////////////////////////////////////////////////
//
const props = defineProps<{ password: string }>();
const emit = defineEmits<{ score: [value: number | null] }>();

////////////////////////////////////////////////////////////////////////
//
const score = ref<number | null>(null);
const warning = ref<string>("");
const suggestions = ref<string[]>([]);

// Cached module reference so we only dynamic-import once.
let _zxcvbn:
  | ((pw: string) => {
      score: number;
      feedback: { warning: string; suggestions: string[] };
    })
  | null = null;
let _debounce: ReturnType<typeof setTimeout> | null = null;

////////////////////////////////////////////////////////////////////////
//
async function evaluate(password: string): Promise<void> {
  if (!password) {
    score.value = null;
    warning.value = "";
    suggestions.value = [];
    emit("score", null);
    return;
  }
  if (!_zxcvbn) {
    const mod = await import("zxcvbn");
    _zxcvbn = mod.default;
  }
  const result = _zxcvbn(password);
  score.value = result.score;
  warning.value = result.feedback.warning;
  suggestions.value = result.feedback.suggestions;
  emit("score", result.score);
}

watch(
  () => props.password,
  (pw) => {
    if (_debounce) clearTimeout(_debounce);
    _debounce = setTimeout(() => evaluate(pw), 200);
  },
);

////////////////////////////////////////////////////////////////////////
//
const SCORE_META: { label: string; bar: string; text: string }[] = [
  { label: "Very weak", bar: "bg-progress-over", text: "text-danger-fg" },
  { label: "Weak", bar: "bg-progress-over", text: "text-danger-fg" },
  { label: "Fair", bar: "bg-progress-behind", text: "text-warning-fg" },
  { label: "Strong", bar: "bg-progress-active", text: "text-fg-muted" },
  { label: "Very strong", bar: "bg-progress-funded", text: "text-fg-muted" },
];
</script>

<template>
  <div v-if="score !== null" class="mt-2 space-y-1.5">
    <!-- 5 bars, one per score level -->
    <div
      class="flex gap-1"
      role="meter"
      :aria-valuenow="score"
      aria-valuemin="0"
      aria-valuemax="4"
    >
      <div
        v-for="i in [0, 1, 2, 3, 4]"
        :key="i"
        class="h-1.5 flex-1 rounded-pill transition-colors duration-base"
        :class="i <= score ? SCORE_META[score].bar : 'bg-surface-strong'"
      />
    </div>

    <!-- Label + warning on the same line -->
    <p class="text-meta" :class="SCORE_META[score].text">
      {{ SCORE_META[score].label
      }}<template v-if="warning"> — {{ warning }}</template>
    </p>

    <!-- Suggestions -->
    <ul
      v-if="suggestions.length"
      class="list-disc pl-4 text-meta text-fg-muted"
    >
      <li v-for="s in suggestions" :key="s">{{ s }}</li>
    </ul>
  </div>
</template>
