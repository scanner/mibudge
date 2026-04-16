//
// Minimal RRULE parser and generator for the subset of RFC 2445
// patterns used by MiBudge (Weekly / Monthly / Yearly funding and
// recurrence schedules).
//
// Produces strings like:
//   RRULE:FREQ=WEEKLY;BYDAY=MO,FR
//   RRULE:FREQ=MONTHLY;INTERVAL=2;BYMONTHDAY=1,15
//   RRULE:FREQ=YEARLY;BYMONTH=5;BYMONTHDAY=15
//

////////////////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////
//
export type Weekday = "MO" | "TU" | "WE" | "TH" | "FR" | "SA" | "SU";

export interface RruleWeekly {
  freq: "WEEKLY";
  interval: 1 | 2 | 4;
  byday: Weekday[];
}

export interface RruleMonthly {
  freq: "MONTHLY";
  interval: 1 | 2 | 3 | 6;
  bymonthday: number[]; // 1–31, or -1 for "last day"
}

export interface RruleYearly {
  freq: "YEARLY";
  interval: 1 | 2;
  bymonth: number; // 1–12
  bymonthday: number; // 1–31, or -1 for "last day"
}

export type RruleParsed = RruleWeekly | RruleMonthly | RruleYearly;

////////////////////////////////////////////////////////////////////////
//
function parseParams(rule: string): Record<string, string> {
  const stripped = rule.startsWith("RRULE:") ? rule.slice(6) : rule;
  const out: Record<string, string> = {};
  for (const part of stripped.split(";")) {
    const eq = part.indexOf("=");
    if (eq !== -1) out[part.slice(0, eq)] = part.slice(eq + 1);
  }
  return out;
}

////////////////////////////////////////////////////////////////////////
//
export function parseRrule(rule: string): RruleParsed | null {
  if (!rule) return null;
  const p = parseParams(rule);
  const interval = p.INTERVAL ? parseInt(p.INTERVAL, 10) : 1;

  switch (p.FREQ) {
    case "WEEKLY": {
      const byday: Weekday[] = p.BYDAY ? (p.BYDAY.split(",") as Weekday[]) : ["MO"];
      return {
        freq: "WEEKLY",
        interval: ([1, 2, 4].includes(interval) ? interval : 1) as 1 | 2 | 4,
        byday,
      };
    }
    case "MONTHLY": {
      const bymonthday = p.BYMONTHDAY ? p.BYMONTHDAY.split(",").map(Number) : [1];
      return {
        freq: "MONTHLY",
        interval: ([1, 2, 3, 6].includes(interval) ? interval : 1) as 1 | 2 | 3 | 6,
        bymonthday,
      };
    }
    case "YEARLY": {
      return {
        freq: "YEARLY",
        interval: (interval === 2 ? 2 : 1) as 1 | 2,
        bymonth: p.BYMONTH ? parseInt(p.BYMONTH, 10) : 1,
        bymonthday: p.BYMONTHDAY ? parseInt(p.BYMONTHDAY, 10) : 1,
      };
    }
    default:
      return null;
  }
}

////////////////////////////////////////////////////////////////////////
//
export function buildRrule(parsed: RruleParsed): string {
  const parts: string[] = [];

  if (parsed.freq === "WEEKLY") {
    parts.push("RRULE:FREQ=WEEKLY");
    if (parsed.interval > 1) parts.push(`INTERVAL=${parsed.interval}`);
    parts.push(`BYDAY=${parsed.byday.join(",")}`);
  } else if (parsed.freq === "MONTHLY") {
    parts.push("RRULE:FREQ=MONTHLY");
    if (parsed.interval > 1) parts.push(`INTERVAL=${parsed.interval}`);
    parts.push(`BYMONTHDAY=${parsed.bymonthday.join(",")}`);
  } else {
    parts.push("RRULE:FREQ=YEARLY");
    if (parsed.interval > 1) parts.push(`INTERVAL=${parsed.interval}`);
    parts.push(`BYMONTH=${parsed.bymonth}`);
    parts.push(`BYMONTHDAY=${parsed.bymonthday}`);
  }

  return parts.join(";");
}

////////////////////////////////////////////////////////////////////////
//
export const WEEKDAY_ORDER: Weekday[] = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"];

export const WEEKDAY_SHORT: Record<Weekday, string> = {
  MO: "Mo",
  TU: "Tu",
  WE: "We",
  TH: "Th",
  FR: "Fr",
  SA: "Sa",
  SU: "Su",
};

export const MONTH_NAMES = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

////////////////////////////////////////////////////////////////////////
//
function ordinal(n: number): string {
  if (n === -1) return "the last day";
  const v = n % 100;
  const suffix = v >= 11 && v <= 13 ? "th" : (["th", "st", "nd", "rd"][v % 10] ?? "th");
  return `the ${n}${suffix}`;
}

////////////////////////////////////////////////////////////////////////
//
export function rruleHuman(rule: string): string {
  const parsed = parseRrule(rule);
  if (!parsed) return rule;

  if (parsed.freq === "WEEKLY") {
    const days = parsed.byday.map((d) => WEEKDAY_SHORT[d]).join(", ");
    if (parsed.interval === 1) return `Every week on ${days}`;
    if (parsed.interval === 2) return `Every 2 weeks on ${days}`;
    return `Every 4 weeks on ${days}`;
  }

  if (parsed.freq === "MONTHLY") {
    const days = parsed.bymonthday.map(ordinal).join(" and ");
    if (parsed.interval === 1) return `Every month on ${days}`;
    if (parsed.interval === 2) return `Every 2 months on ${days}`;
    if (parsed.interval === 3) return `Every quarter on ${days}`;
    return `Every 6 months on ${days}`;
  }

  // YEARLY
  const month = MONTH_NAMES[(parsed.bymonth ?? 1) - 1];
  const day = ordinal(parsed.bymonthday ?? 1);
  if (parsed.interval === 1) return `Every year on ${month} ${day}`;
  return `Every 2 years on ${month} ${day}`;
}

////////////////////////////////////////////////////////////////////////
//
// Default RRULE for new budgets -- first of every month.
//
export const DEFAULT_RRULE = "RRULE:FREQ=MONTHLY;BYMONTHDAY=1";
