//
// Date display helper tests.  The suite runs with the browser zone set
// to America/New_York (vitest.config.ts); tests vary the profile zone
// passed to each helper, and freeze "now" where the result depends on it.
//

// 3rd party imports
//
import { afterEach, describe, expect, it, vi } from "vitest";

// app imports
//
import { formatDateHeader, formatTxDateLong, todayDateStr, txDateStr } from "@/utils/dates";

////////////////////////////////////////////////////////////////////////
//
afterEach(() => {
  vi.useRealTimers();
});

////////////////////////////////////////////////////////////////////////
//
describe("todayDateStr", () => {
  // GIVEN: an instant that is still the previous evening in the Americas
  // WHEN:  today's date is computed for a profile timezone
  // THEN:  it is the calendar date in that zone, not the browser's
  //
  it.each([
    ["America/Los_Angeles", "2026-09-23"],
    ["America/New_York", "2026-09-23"],
    ["UTC", "2026-09-24"],
    ["Asia/Tokyo", "2026-09-24"],
  ])("in %s is %s", (tz, expected) => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-24T03:30:00Z"));
    expect(todayDateStr(tz)).toBe(expected);
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("txDateStr", () => {
  // GIVEN: a transaction timestamp
  // WHEN:  its date is taken in a profile timezone
  // THEN:  the calendar date in that zone is returned
  //
  it.each([
    ["2024-10-15T07:00:00Z", "America/Los_Angeles", "2024-10-15"],
    ["2024-10-15T04:00:00Z", "America/Los_Angeles", "2024-10-14"],
    ["2024-10-15T04:00:00Z", "America/New_York", "2024-10-15"],
    ["2024-10-15T23:30:00Z", "Asia/Tokyo", "2024-10-16"],
  ])("%s in %s is %s", (iso, tz, expected) => {
    expect(txDateStr(iso, tz)).toBe(expected);
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("formatDateHeader", () => {
  // GIVEN: a date string and today's date string
  // WHEN:  the list header for that date is rendered in the browser's
  //        own timezone
  // THEN:  it reads "Today", "Yesterday", a short date, or a short date
  //        with the year when the year differs
  //
  it.each([
    ["2026-09-24", "2026-09-24", "Today"],
    ["2026-09-23", "2026-09-24", "Yesterday"],
    ["2026-02-28", "2026-03-01", "Yesterday"],
    // 2026-03-08 is the US spring-forward day.
    ["2026-03-08", "2026-03-09", "Yesterday"],
    ["2025-12-31", "2026-01-01", "Yesterday"],
    ["2026-07-04", "2026-09-24", "Jul 4"],
    ["2025-12-25", "2026-09-24", "Dec 25, 2025"],
  ])("%s with today %s → %s", (date, today, expected) => {
    expect(formatDateHeader(date, today, "America/New_York")).toBe(expected);
  });

  // GIVEN: a browser in America/New_York and a profile in
  //        America/Los_Angeles
  // WHEN:  the header for 2026-07-04 is rendered
  // THEN:  it reads "Jul 4"
  //
  // Known bug: `formatDateHeader` (src/utils/dates.ts) parses the date
  // as browser-local midnight and formats it in the profile zone, so a
  // profile zone west of the browser shows the previous day ("Jul 3").
  // Convert to `it(...)` when the bug is fixed.
  //
  it.fails("shows the same date when browser and profile timezones differ", () => {
    expect(formatDateHeader("2026-07-04", "2026-09-24", "America/Los_Angeles")).toBe("Jul 4");
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("formatTxDateLong", () => {
  // GIVEN: a transaction timestamp at midnight in the profile timezone
  // WHEN:  the long date is rendered
  // THEN:  only the date is shown
  //
  it("omits the time at local midnight", () => {
    expect(formatTxDateLong("2024-10-15T07:00:00Z", "America/Los_Angeles")).toBe(
      "Tuesday, October 15, 2024",
    );
  });

  // GIVEN: a transaction timestamp that is not midnight in the profile
  //        timezone
  // WHEN:  the long date is rendered
  // THEN:  the local time is appended
  //
  it("appends the time otherwise", () => {
    expect(formatTxDateLong("2024-10-15T21:34:00Z", "America/Los_Angeles")).toBe(
      "Tuesday, October 15, 2024 at 2:34 PM",
    );
  });
});
