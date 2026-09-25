//
// Date helper tests (`src/domain/dates.ts`).  The suite runs with the
// browser zone set to America/New_York (vitest.config.ts); tests vary
// the profile zone passed to each helper, stub the browser zone where
// the result must not depend on it, and freeze "now" where it matters.
//

// 3rd party imports
//
import { afterEach, describe, expect, it, vi } from "vitest";

// app imports
//
import {
  addDays,
  daysBetween,
  formatDateHeader,
  formatInstantDate,
  formatLocalDate,
  formatTxDateLong,
  parseLocalDate,
  toLocalDate,
  todayDateStr,
  txDateStr,
} from "@/domain/dates";
import type { LocalDate } from "@/domain/dates";

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

  // GIVEN: an explicit clock value
  // WHEN:  today's date is computed with it
  // THEN:  the date follows the given instant, not the system clock
  //
  it("uses the instant it is given", () => {
    expect(todayDateStr("UTC", new Date("2020-02-29T12:00:00Z"))).toBe("2020-02-29");
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("parseLocalDate", () => {
  // GIVEN: a date-only string
  // WHEN:  it is parsed in a browser east or west of UTC
  // THEN:  the result is local midnight on that same calendar day
  //
  it.each(["Pacific/Honolulu", "America/New_York", "UTC", "Asia/Tokyo"])("in %s", (tz) => {
    // `vi.stubEnv` changes the process zone for this test only;
    // `unstubEnvs` in vitest.config.ts restores America/New_York.
    //
    vi.stubEnv("TZ", tz);
    expect(Intl.DateTimeFormat().resolvedOptions().timeZone).toBe(tz);
    const d = parseLocalDate("2026-08-01");
    expect([d.getFullYear(), d.getMonth(), d.getDate(), d.getHours()]).toEqual([2026, 7, 1, 0]);
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("toLocalDate", () => {
  // GIVEN: a value from a date-only API field
  // WHEN:  it is validated as a calendar date
  // THEN:  a real `YYYY-MM-DD` date is kept, anything else is null
  //
  it.each([
    ["2026-08-01", "2026-08-01"],
    ["2024-02-29", "2024-02-29"],
    ["2026-02-29", null],
    ["2026-13-01", null],
    ["2026-08-01T00:00:00Z", null],
    ["", null],
    [null, null],
    [undefined, null],
  ])("%j → %j", (value, expected) => {
    expect(toLocalDate(value)).toBe(expected);
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("addDays / daysBetween", () => {
  // GIVEN: a calendar date
  // WHEN:  it is shifted by a number of days, and the distance back is measured
  // THEN:  month, year and DST boundaries are crossed exactly
  //
  it.each([
    ["2026-03-01", -1, "2026-02-28"],
    ["2024-03-01", -1, "2024-02-29"],
    ["2025-12-31", 1, "2026-01-01"],
    // 2026-03-08 is the US spring-forward day.
    ["2026-03-07", 2, "2026-03-09"],
    ["2026-11-01", 30, "2026-12-01"],
  ])("%s + %i = %s", (from, days, to) => {
    expect(addDays(from as LocalDate, days)).toBe(to);
    expect(daysBetween(from as LocalDate, to as LocalDate)).toBe(days);
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("formatLocalDate", () => {
  // GIVEN: a calendar date such as a goal's target date
  // WHEN:  it is formatted in a browser east or west of UTC
  // THEN:  the same calendar day is shown in every zone
  //
  it.each(["Pacific/Honolulu", "America/Los_Angeles", "UTC", "Asia/Tokyo"])("in %s", (tz) => {
    vi.stubEnv("TZ", tz);
    const opts = { month: "short", day: "numeric", year: "numeric" } as const;
    expect(formatLocalDate("2026-08-01" as LocalDate, opts)).toBe("Aug 1, 2026");
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("formatInstantDate", () => {
  // GIVEN: an instant late in the evening in New York
  // WHEN:  its date is formatted in the browser zone and in a given zone
  // THEN:  each shows the calendar date in that zone
  //
  it("formats in the browser zone or the given zone", () => {
    const iso = "2026-08-02T02:00:00Z";
    const opts = { month: "short", day: "numeric" } as const;
    expect(formatInstantDate(iso, opts)).toBe("Aug 1");
    expect(formatInstantDate(iso, opts, "Asia/Tokyo")).toBe("Aug 2");
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
    expect(formatDateHeader(date, today)).toBe(expected);
  });

  // GIVEN: a browser whose zone differs from the profile zone that
  //        produced the date strings
  // WHEN:  the header for 2026-07-04 is rendered
  // THEN:  it reads "Jul 4" in every browser zone
  //
  it.each(["Pacific/Honolulu", "America/Los_Angeles", "Asia/Tokyo"])(
    "shows the same date when browser and profile timezones differ (%s)",
    (tz) => {
      vi.stubEnv("TZ", tz);
      expect(formatDateHeader("2026-07-04", "2026-09-24")).toBe("Jul 4");
    },
  );

  // GIVEN: a string that is not a calendar date
  // WHEN:  a header is rendered for it
  // THEN:  the string is shown unchanged
  //
  it("passes through a malformed date", () => {
    expect(formatDateHeader("not-a-date", "2026-09-24")).toBe("not-a-date");
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

  // GIVEN: a transaction timestamp that is not midnight, and a locale
  // WHEN:  the long date is rendered in that locale
  // THEN:  the date, the time and the word joining them are all in
  //        that locale
  //
  it.each([
    ["de-DE", "Dienstag, 15. Oktober 2024 um 14:34"],
    ["fr-FR", "mardi 15 octobre 2024 à 14:34"],
  ])("joins date and time in the %s locale", (locale, expected) => {
    expect(formatTxDateLong("2024-10-15T21:34:00Z", "America/Los_Angeles", locale)).toBe(expected);
  });
});
