//
// `useDateGroupedRows` / `groupRowsByDate` tests: calendar-date groups
// in the profile timezone, newest first.
//

// 3rd party imports
//
import { describe, expect, it } from "vitest";
import { ref } from "vue";

// app imports
//
import {
  groupRowsByDate,
  useDateGroupedRows,
} from "@/composables/useDateGroupedRows";

////////////////////////////////////////////////////////////////////////
//
const NOW = new Date("2026-09-24T15:00:00Z");

interface Row {
  id: string;
  at: string;
}

////////////////////////////////////////////////////////////////////////
//
describe("groupRowsByDate", () => {
  // GIVEN: rows on three dates, out of order
  // WHEN:  they are grouped in the profile timezone
  // THEN:  groups are newest first with Today / Yesterday / short-date
  //        labels, and rows within a group are newest first
  //
  it("groups and orders by date", () => {
    const rows: Row[] = [
      { id: "old", at: "2026-07-04T16:00:00Z" },
      { id: "today-early", at: "2026-09-24T13:00:00Z" },
      { id: "yesterday", at: "2026-09-23T16:00:00Z" },
      { id: "today-late", at: "2026-09-24T14:00:00Z" },
    ];

    const groups = groupRowsByDate(rows, (r) => r.at, "America/New_York", NOW);

    expect(groups.map((g) => [g.date, g.label])).toEqual([
      ["2026-09-24", "Today"],
      ["2026-09-23", "Yesterday"],
      ["2026-07-04", "Jul 4"],
    ]);
    expect(groups[0].rows.map((r) => r.id)).toEqual([
      "today-late",
      "today-early",
    ]);
  });

  // GIVEN: an instant late in the evening in Los Angeles
  // WHEN:  it is grouped in Los Angeles and in Tokyo
  // THEN:  it falls on that zone's calendar date
  //
  it("uses the profile timezone", () => {
    const rows: Row[] = [{ id: "x", at: "2026-09-23T05:30:00Z" }];
    expect(
      groupRowsByDate(rows, (r) => r.at, "America/Los_Angeles", NOW)[0].date,
    ).toBe("2026-09-22");
    expect(groupRowsByDate(rows, (r) => r.at, "Asia/Tokyo", NOW)[0].date).toBe(
      "2026-09-23",
    );
  });

  // GIVEN: rows with equal instants
  // WHEN:  they are grouped
  // THEN:  they keep their input order
  //
  it("keeps input order for equal instants", () => {
    const at = "2026-09-24T12:00:00Z";
    const rows: Row[] = [
      { id: "a", at },
      { id: "b", at },
    ];
    expect(
      groupRowsByDate(rows, (r) => r.at, "UTC", NOW)[0].rows.map((r) => r.id),
    ).toEqual(["a", "b"]);
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("useDateGroupedRows", () => {
  // GIVEN: a reactive list and timezone
  // WHEN:  the list changes
  // THEN:  the groups follow
  //
  it("recomputes when the rows change", () => {
    const rows = ref<Row[]>([]);
    const groups = useDateGroupedRows(() => rows.value, {
      instantOf: (r) => r.at,
      timezone: () => "UTC",
      now: () => NOW,
    });
    expect(groups.value).toEqual([]);
    rows.value = [{ id: "a", at: "2026-09-24T01:00:00Z" }];
    expect(groups.value.map((g) => g.label)).toEqual(["Today"]);
  });
});
