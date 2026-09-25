//
// `useDateGroupedRows`: group list rows under date headers ("Today",
// "Yesterday", "Apr 15").  Composables layer.
//
// Each row's instant is placed on its calendar date in the profile
// timezone.  Groups are newest first, and rows within a group are
// newest first (rows with equal instants keep their input order).
//

// 3rd party imports
//
import { computed } from "vue";
import type { ComputedRef } from "vue";

// app imports
//
import type { LocalDate } from "@/domain/dates";
import { formatDateHeader, todayDateStr, txDateStr } from "@/domain/dates";

////////////////////////////////////////////////////////////////////////
//
export interface DateGroup<T> {
  date: LocalDate;
  label: string;
  rows: T[];
}

export interface UseDateGroupedRowsOptions<T> {
  // The row's instant (ISO datetime).
  instantOf: (row: T) => string;
  timezone: () => string;
  // The clock, for "Today" / "Yesterday".  Defaults to the system clock.
  now?: () => Date;
}

////////////////////////////////////////////////////////////////////////
//
export function groupRowsByDate<T>(
  rows: readonly T[],
  instantOf: (row: T) => string,
  timezone: string,
  now: Date = new Date(),
): DateGroup<T>[] {
  const today = todayDateStr(timezone, now);
  const groups = new Map<
    LocalDate,
    { group: DateGroup<T>; instants: string[] }
  >();

  for (const row of rows) {
    const instant = instantOf(row);
    const date = txDateStr(instant, timezone);
    let entry = groups.get(date);
    if (!entry) {
      entry = {
        group: { date, label: formatDateHeader(date, today), rows: [] },
        instants: [],
      };
      groups.set(date, entry);
    }
    entry.group.rows.push(row);
    entry.instants.push(instant);
  }

  const out: DateGroup<T>[] = [];
  for (const { group, instants } of groups.values()) {
    const order = group.rows.map((row, i) => ({
      row,
      instant: instants[i],
      i,
    }));
    order.sort((a, b) =>
      a.instant > b.instant ? -1 : a.instant < b.instant ? 1 : a.i - b.i,
    );
    out.push({ ...group, rows: order.map((o) => o.row) });
  }
  return out.sort((a, b) => (a.date > b.date ? -1 : a.date < b.date ? 1 : 0));
}

////////////////////////////////////////////////////////////////////////
//
export function useDateGroupedRows<T>(
  rows: () => readonly T[],
  options: UseDateGroupedRowsOptions<T>,
): ComputedRef<DateGroup<T>[]> {
  return computed(() =>
    groupRowsByDate(
      rows(),
      options.instantOf,
      options.timezone(),
      options.now?.() ?? new Date(),
    ),
  );
}
