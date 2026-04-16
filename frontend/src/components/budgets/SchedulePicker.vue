<script setup lang="ts">
//
// SchedulePicker — RRULE producer/consumer for budget forms.
// (UI_SPEC §5.1)
//
// Accepts a RRULE string via v-model and emits an updated string when
// any selector changes.  Three frequency modes: Weekly, Monthly,
// Yearly.
//

// 3rd party imports
//
import { computed, ref, watch } from "vue";

// app imports
//
import {
  buildRrule,
  DEFAULT_RRULE,
  MONTH_NAMES,
  parseRrule,
  rruleHuman,
  WEEKDAY_ORDER,
  WEEKDAY_SHORT,
} from "@/utils/rrule";
import type { RruleMonthly, RruleWeekly, RruleYearly, Weekday } from "@/utils/rrule";

////////////////////////////////////////////////////////////////////////
//
interface Props {
  modelValue: string;
  label: string;
}

const props = defineProps<Props>();
const emit = defineEmits<{ (e: "update:modelValue", val: string): void }>();

////////////////////////////////////////////////////////////////////////
//
// Internal state mirrors the parsed RRULE.  Initialised from
// modelValue; kept in sync by a watcher.
//
type Freq = "WEEKLY" | "MONTHLY" | "YEARLY";

const freq = ref<Freq>("MONTHLY");
const weeklyInterval = ref<1 | 2 | 4>(1);
const weeklyDays = ref<Set<Weekday>>(new Set(["MO"]));
const monthlyInterval = ref<1 | 2 | 3 | 6>(1);
const monthlyDays = ref<Set<number>>(new Set([1]));
const yearlyInterval = ref<1 | 2>(1);
const yearlyMonth = ref<number>(1);
const yearlyDay = ref<number>(1);

////////////////////////////////////////////////////////////////////////
//
function applyParsed(rule: string) {
  const parsed = parseRrule(rule ?? DEFAULT_RRULE) ?? parseRrule(DEFAULT_RRULE)!;
  freq.value = parsed.freq;
  if (parsed.freq === "WEEKLY") {
    weeklyInterval.value = parsed.interval;
    weeklyDays.value = new Set(parsed.byday);
  } else if (parsed.freq === "MONTHLY") {
    monthlyInterval.value = parsed.interval;
    monthlyDays.value = new Set(parsed.bymonthday);
  } else {
    yearlyInterval.value = parsed.interval;
    yearlyMonth.value = parsed.bymonth;
    yearlyDay.value = parsed.bymonthday;
  }
}

applyParsed(props.modelValue);

watch(
  () => props.modelValue,
  (val) => {
    if (val !== currentRrule.value) applyParsed(val);
  },
);

////////////////////////////////////////////////////////////////////////
//
// Rebuild and emit whenever internal state changes.
//
const currentRrule = computed((): string => {
  if (freq.value === "WEEKLY") {
    const days = [...weeklyDays.value].filter((d): d is Weekday =>
      WEEKDAY_ORDER.includes(d as Weekday),
    );
    const parsed: RruleWeekly = {
      freq: "WEEKLY",
      interval: weeklyInterval.value,
      byday: days.length > 0 ? days : ["MO"],
    };
    return buildRrule(parsed);
  }
  if (freq.value === "MONTHLY") {
    const days = [...monthlyDays.value].sort((a, b) => a - b);
    const parsed: RruleMonthly = {
      freq: "MONTHLY",
      interval: monthlyInterval.value,
      bymonthday: days.length > 0 ? days : [1],
    };
    return buildRrule(parsed);
  }
  const parsed: RruleYearly = {
    freq: "YEARLY",
    interval: yearlyInterval.value,
    bymonth: yearlyMonth.value,
    bymonthday: yearlyDay.value,
  };
  return buildRrule(parsed);
});

watch(currentRrule, (val) => emit("update:modelValue", val));

////////////////////////////////////////////////////////////////////////
//
function setFreq(f: Freq) {
  freq.value = f;
}

function toggleWeekday(d: Weekday) {
  const s = new Set(weeklyDays.value);
  if (s.has(d) && s.size > 1) s.delete(d);
  else s.add(d);
  weeklyDays.value = s;
}

function toggleMonthDay(d: number) {
  const s = new Set(monthlyDays.value);
  if (s.has(d) && s.size > 1) s.delete(d);
  else s.add(d);
  monthlyDays.value = s;
}

////////////////////////////////////////////////////////////////////////
//
const YEARLY_DAY_OPTIONS = [1, 5, 10, 15, 20, 25, -1] as const;

const WEEKLY_INTERVAL_OPTIONS: { value: 1 | 2 | 4; label: string }[] = [
  { value: 1, label: "Every week" },
  { value: 2, label: "Every 2 weeks" },
  { value: 4, label: "Every 4 weeks" },
];

const MONTHLY_INTERVAL_OPTIONS: { value: 1 | 2 | 3 | 6; label: string }[] = [
  { value: 1, label: "Every month" },
  { value: 2, label: "Every 2 months" },
  { value: 3, label: "Every quarter" },
  { value: 6, label: "Every 6 months" },
];

function yearlyDayLabel(n: number): string {
  if (n === -1) return "Last day";
  const v = n % 100;
  const suffix = v >= 11 && v <= 13 ? "th" : (["th", "st", "nd", "rd"][v % 10] ?? "th");
  return `${n}${suffix}`;
}
</script>

<template>
  <div class="rounded-card border border-neutral-200 bg-white">
    <!-- Label -->
    <div class="px-4 pt-3">
      <p class="text-[11px] font-semibold uppercase tracking-wider text-neutral-500">
        {{ label }}
      </p>
    </div>

    <!-- Frequency tabs -->
    <div class="mt-2 flex gap-1 border-b border-neutral-100 px-4 pb-0">
      <button
        v-for="f in ['WEEKLY', 'MONTHLY', 'YEARLY'] as Freq[]"
        :key="f"
        type="button"
        class="rounded-t-md px-3 py-1.5 text-sm font-medium transition-colors"
        :class="
          freq === f
            ? 'border-b-2 border-ocean-400 text-ocean-600'
            : 'text-neutral-500 hover:text-neutral-700'
        "
        @click="setFreq(f)"
      >
        {{ f === "WEEKLY" ? "Weekly" : f === "MONTHLY" ? "Monthly" : "Yearly" }}
      </button>
    </div>

    <div class="space-y-3 p-4">
      <!-- ── WEEKLY ── -->
      <template v-if="freq === 'WEEKLY'">
        <select
          :value="weeklyInterval"
          class="w-full rounded-subcard border border-neutral-200 px-3 py-2 text-sm text-neutral-900"
          @change="weeklyInterval = Number(($event.target as HTMLSelectElement).value) as 1 | 2 | 4"
        >
          <option v-for="opt in WEEKLY_INTERVAL_OPTIONS" :key="opt.value" :value="opt.value">
            {{ opt.label }}
          </option>
        </select>

        <div class="flex gap-1.5">
          <button
            v-for="d in WEEKDAY_ORDER"
            :key="d"
            type="button"
            class="flex-1 rounded-full py-1.5 text-xs font-medium transition-colors"
            :class="
              weeklyDays.has(d)
                ? 'bg-ocean-400 text-white'
                : 'bg-neutral-100 text-neutral-600 hover:bg-neutral-200'
            "
            @click="toggleWeekday(d)"
          >
            {{ WEEKDAY_SHORT[d] }}
          </button>
        </div>
      </template>

      <!-- ── MONTHLY ── -->
      <template v-else-if="freq === 'MONTHLY'">
        <select
          :value="monthlyInterval"
          class="w-full rounded-subcard border border-neutral-200 px-3 py-2 text-sm text-neutral-900"
          @change="
            monthlyInterval = Number(($event.target as HTMLSelectElement).value) as 1 | 2 | 3 | 6
          "
        >
          <option v-for="opt in MONTHLY_INTERVAL_OPTIONS" :key="opt.value" :value="opt.value">
            {{ opt.label }}
          </option>
        </select>

        <!-- Day-of-month grid: 1–31 + Last -->
        <div class="grid grid-cols-8 gap-1">
          <button
            v-for="d in Array.from({ length: 31 }, (_, i) => i + 1)"
            :key="d"
            type="button"
            class="rounded-md py-1 text-xs font-medium transition-colors"
            :class="
              monthlyDays.has(d)
                ? 'bg-ocean-400 text-white'
                : 'bg-neutral-100 text-neutral-600 hover:bg-neutral-200'
            "
            @click="toggleMonthDay(d)"
          >
            {{ d }}
          </button>
          <button
            type="button"
            class="col-span-2 rounded-md py-1 text-xs font-medium transition-colors"
            :class="
              monthlyDays.has(-1)
                ? 'bg-ocean-400 text-white'
                : 'bg-neutral-100 text-neutral-600 hover:bg-neutral-200'
            "
            @click="toggleMonthDay(-1)"
          >
            Last
          </button>
        </div>
      </template>

      <!-- ── YEARLY ── -->
      <template v-else>
        <select
          :value="yearlyInterval"
          class="w-full rounded-subcard border border-neutral-200 px-3 py-2 text-sm text-neutral-900"
          @change="yearlyInterval = Number(($event.target as HTMLSelectElement).value) as 1 | 2"
        >
          <option :value="1">Every year</option>
          <option :value="2">Every 2 years</option>
        </select>

        <div class="grid grid-cols-2 gap-2">
          <select
            :value="yearlyMonth"
            class="rounded-subcard border border-neutral-200 px-3 py-2 text-sm text-neutral-900"
            @change="yearlyMonth = Number(($event.target as HTMLSelectElement).value)"
          >
            <option v-for="(name, idx) in MONTH_NAMES" :key="idx" :value="idx + 1">
              {{ name }}
            </option>
          </select>

          <select
            :value="yearlyDay"
            class="rounded-subcard border border-neutral-200 px-3 py-2 text-sm text-neutral-900"
            @change="yearlyDay = Number(($event.target as HTMLSelectElement).value)"
          >
            <option v-for="d in YEARLY_DAY_OPTIONS" :key="d" :value="d">
              {{ yearlyDayLabel(d) }}
            </option>
          </select>
        </div>
      </template>

      <!-- Preview block -->
      <div class="rounded-subcard bg-neutral-50 px-3 py-2">
        <p class="text-sm text-neutral-700">{{ rruleHuman(currentRrule) }}</p>
        <p class="mt-0.5 font-mono text-[11px] text-neutral-400">{{ currentRrule }}</p>
      </div>
    </div>
  </div>
</template>
