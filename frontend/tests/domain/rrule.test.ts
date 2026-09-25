//
// RRULE helper tests: parse / build round-trips, human-readable text,
// DTSTART handling, and interval-only reduction (`src/domain/rrule.ts`).
//

// 3rd party imports
//
import { describe, expect, it, vi } from "vitest";

// app imports
//
import {
  buildRrule,
  combineDtstart,
  extractDtstart,
  parseRrule,
  rruleHuman,
  stripToIntervalOnly,
} from "@/domain/rrule";

////////////////////////////////////////////////////////////////////////
//
describe("parseRrule / buildRrule", () => {
  // GIVEN: a rule in the canonical form MiBudge writes
  // WHEN:  it is parsed and rebuilt
  // THEN:  the rebuilt rule is identical to the original
  //
  it.each([
    "RRULE:FREQ=WEEKLY",
    "RRULE:FREQ=WEEKLY;BYDAY=MO,FR",
    "RRULE:FREQ=WEEKLY;INTERVAL=2;BYDAY=TU",
    "RRULE:FREQ=WEEKLY;INTERVAL=4;BYDAY=SU",
    "RRULE:FREQ=MONTHLY",
    "RRULE:FREQ=MONTHLY;BYMONTHDAY=1",
    "RRULE:FREQ=MONTHLY;INTERVAL=2;BYMONTHDAY=1,15",
    "RRULE:FREQ=MONTHLY;INTERVAL=6;BYMONTHDAY=-1",
    "RRULE:FREQ=YEARLY;BYMONTH=5;BYMONTHDAY=15",
    "RRULE:FREQ=YEARLY;INTERVAL=2;BYMONTH=12;BYMONTHDAY=-1",
  ])("round-trips %s", (rule) => {
    const parsed = parseRrule(rule);
    expect(parsed).not.toBeNull();
    expect(buildRrule(parsed!)).toBe(rule);
  });

  // GIVEN: a rule preceded by a DTSTART line
  // WHEN:  it is parsed
  // THEN:  the RRULE line is parsed and DTSTART is ignored
  //
  it("parses the RRULE line of a DTSTART + RRULE pair", () => {
    expect(
      parseRrule("DTSTART:20260101T000000Z\nRRULE:FREQ=MONTHLY;BYMONTHDAY=5"),
    ).toEqual({
      freq: "MONTHLY",
      interval: 1,
      bymonthday: [5],
    });
  });

  // GIVEN: a rule without the `RRULE:` prefix
  // WHEN:  it is parsed
  // THEN:  it parses the same as the prefixed form
  //
  it("accepts a rule without the RRULE: prefix", () => {
    expect(parseRrule("FREQ=WEEKLY;BYDAY=WE")).toEqual({
      freq: "WEEKLY",
      interval: 1,
      byday: ["WE"],
    });
  });

  // GIVEN: an interval the pickers do not offer
  // WHEN:  the rule is parsed
  // THEN:  the interval falls back to 1
  //
  it.each([
    ["RRULE:FREQ=WEEKLY;INTERVAL=3", 1],
    ["RRULE:FREQ=MONTHLY;INTERVAL=4", 1],
    ["RRULE:FREQ=YEARLY;INTERVAL=5", 1],
  ])("coerces the interval of %s to %i", (rule, interval) => {
    expect(parseRrule(rule)?.interval).toBe(interval);
  });

  // GIVEN: a yearly rule with no BYMONTH / BYMONTHDAY
  // WHEN:  it is parsed
  // THEN:  month and day default to January 1st
  //
  it("defaults yearly month and day to 1", () => {
    expect(parseRrule("RRULE:FREQ=YEARLY")).toEqual({
      freq: "YEARLY",
      interval: 1,
      bymonth: 1,
      bymonthday: 1,
    });
  });

  // GIVEN: an empty rule or a frequency MiBudge does not use
  // WHEN:  it is parsed
  // THEN:  the result is null
  //
  it.each(["", "RRULE:FREQ=DAILY", "garbage"])(
    "returns null for %j",
    (rule) => {
      expect(parseRrule(rule)).toBeNull();
    },
  );
});

////////////////////////////////////////////////////////////////////////
//
describe("rruleHuman", () => {
  // GIVEN: a funding or recurrence rule
  // WHEN:  it is rendered for display
  // THEN:  the text names the frequency, interval and day(s); explicit
  //        BY* parts take precedence over the DTSTART anchor
  //
  it.each([
    ["RRULE:FREQ=WEEKLY", "Every week"],
    ["RRULE:FREQ=WEEKLY;BYDAY=MO,FR", "Every week on Mo, Fr"],
    ["RRULE:FREQ=WEEKLY;INTERVAL=2", "Every 2 weeks"],
    // 2026-09-14 is a Monday.
    [
      "DTSTART:20260914T000000Z\nRRULE:FREQ=WEEKLY;INTERVAL=2",
      "Every 2 weeks on Mo",
    ],
    [
      "DTSTART:20260914T000000Z\nRRULE:FREQ=WEEKLY;BYDAY=TH",
      "Every week on Th",
    ],
    ["RRULE:FREQ=MONTHLY", "Every month"],
    [
      "RRULE:FREQ=MONTHLY;BYMONTHDAY=1,15",
      "Every month on the 1st and the 15th",
    ],
    [
      "RRULE:FREQ=MONTHLY;INTERVAL=3;BYMONTHDAY=-1",
      "Every 3 months on the last day",
    ],
    [
      "RRULE:FREQ=MONTHLY;BYMONTHDAY=2,3,11,12,13,21,22,23",
      "Every month on the 2nd and the 3rd and the 11th and the 12th and the 13th" +
        " and the 21st and the 22nd and the 23rd",
    ],
    ["DTSTART:20260122T000000Z\nRRULE:FREQ=MONTHLY", "Every month on the 22nd"],
    [
      "DTSTART:20260122T000000Z\nRRULE:FREQ=MONTHLY;BYMONTHDAY=1",
      "Every month on the 1st",
    ],
    ["RRULE:FREQ=YEARLY", "Every year"],
    ["RRULE:FREQ=YEARLY;BYMONTH=5;BYMONTHDAY=15", "Every year on May the 15th"],
    [
      "DTSTART:20261103T000000Z\nRRULE:FREQ=YEARLY;INTERVAL=2",
      "Every 2 years on November the 3rd",
    ],
    ["RRULE:FREQ=DAILY", "RRULE:FREQ=DAILY"],
  ])("%j → %j", (rule, text) => {
    expect(rruleHuman(rule)).toBe(text);
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("DTSTART helpers", () => {
  // GIVEN: a date and a rule
  // WHEN:  they are combined and then split again
  // THEN:  the original date and rule come back
  //
  it("combineDtstart and extractDtstart round-trip", () => {
    const combined = combineDtstart("RRULE:FREQ=MONTHLY", "2026-10-01");
    expect(combined).toBe("DTSTART:20261001T000000Z\nRRULE:FREQ=MONTHLY");
    expect(extractDtstart(combined)).toEqual({
      dtstart: "2026-10-01",
      rrule: "RRULE:FREQ=MONTHLY",
    });
  });

  // GIVEN: a rule with no DTSTART line
  // WHEN:  DTSTART is extracted
  // THEN:  it is null and the rule is unchanged
  //
  it("extractDtstart without DTSTART", () => {
    expect(extractDtstart("RRULE:FREQ=WEEKLY")).toEqual({
      dtstart: null,
      rrule: "RRULE:FREQ=WEEKLY",
    });
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("stripToIntervalOnly", () => {
  // GIVEN: a rule with BY* parts
  // WHEN:  it is reduced to interval-only form
  // THEN:  only FREQ and a non-default INTERVAL remain
  //
  it.each([
    [
      "RRULE:FREQ=MONTHLY;INTERVAL=2;BYMONTHDAY=1,15",
      "RRULE:FREQ=MONTHLY;INTERVAL=2",
    ],
    ["RRULE:FREQ=WEEKLY;BYDAY=MO", "RRULE:FREQ=WEEKLY"],
    ["RRULE:FREQ=YEARLY;BYMONTH=5;BYMONTHDAY=15", "RRULE:FREQ=YEARLY"],
    ["RRULE:FREQ=MONTHLY", "RRULE:FREQ=MONTHLY"],
    ["RRULE:FREQ=DAILY;BYHOUR=3", "RRULE:FREQ=DAILY;BYHOUR=3"],
  ])("%j → %j", (rule, expected) => {
    expect(stripToIntervalOnly(rule)).toBe(expected);
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("rruleHuman across browser zones", () => {
  // GIVEN: a rule anchored by a DTSTART date and no BY* parts
  // WHEN:  it is rendered in a browser west of UTC
  // THEN:  the anchor's weekday / day of month is the DTSTART calendar day
  //
  it.each([
    [
      "DTSTART:20260914T000000Z\nRRULE:FREQ=WEEKLY;INTERVAL=2",
      "Every 2 weeks on Mo",
    ],
    ["DTSTART:20260122T000000Z\nRRULE:FREQ=MONTHLY", "Every month on the 22nd"],
    [
      "DTSTART:20261103T000000Z\nRRULE:FREQ=YEARLY",
      "Every year on November the 3rd",
    ],
  ])("%j → %j in Pacific/Honolulu", (rule, text) => {
    vi.stubEnv("TZ", "Pacific/Honolulu");
    expect(rruleHuman(rule)).toBe(text);
  });
});
