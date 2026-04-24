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
  const rruleLine = rule.split("\n").find((l) => l.startsWith("RRULE:")) ?? rule;
  const p = parseParams(rruleLine);
  const interval = p.INTERVAL ? parseInt(p.INTERVAL, 10) : 1;

  switch (p.FREQ) {
    case "WEEKLY": {
      const byday: Weekday[] = p.BYDAY ? (p.BYDAY.split(",") as Weekday[]) : [];
      return {
        freq: "WEEKLY",
        interval: ([1, 2, 4].includes(interval) ? interval : 1) as 1 | 2 | 4,
        byday,
      };
    }
    case "MONTHLY": {
      const bymonthday = p.BYMONTHDAY ? p.BYMONTHDAY.split(",").map(Number) : [];
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
    if (parsed.byday.length > 0) parts.push(`BYDAY=${parsed.byday.join(",")}`);
  } else if (parsed.freq === "MONTHLY") {
    parts.push("RRULE:FREQ=MONTHLY");
    if (parsed.interval > 1) parts.push(`INTERVAL=${parsed.interval}`);
    if (parsed.bymonthday.length > 0) parts.push(`BYMONTHDAY=${parsed.bymonthday.join(",")}`);
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

  const { dtstart } = extractDtstart(rule);
  const dtstartDay = dtstart ? new Date(dtstart + "T00:00:00").getDate() : null;

  let text: string;

  if (parsed.freq === "WEEKLY") {
    const prefix = parsed.interval === 1 ? "Every week" : `Every ${parsed.interval} weeks`;
    if (parsed.byday.length === 0) {
      text = prefix;
    } else {
      const days = parsed.byday.map((d) => WEEKDAY_SHORT[d]).join(", ");
      text = `${prefix} on ${days}`;
    }
  } else if (parsed.freq === "MONTHLY") {
    const prefix = parsed.interval === 1 ? "Every month" : `Every ${parsed.interval} months`;
    if (dtstartDay != null) {
      text = `${prefix} on ${ordinal(dtstartDay)}`;
    } else if (parsed.bymonthday.length === 0) {
      text = prefix;
    } else {
      const days = parsed.bymonthday.map(ordinal).join(" and ");
      text = `${prefix} on ${days}`;
    }
  } else {
    const prefix = parsed.interval === 1 ? "Every year" : `Every ${parsed.interval} years`;
    const month = MONTH_NAMES[(parsed.bymonth ?? 1) - 1];
    const day = ordinal(parsed.bymonthday ?? 1);
    text = `${prefix} on ${month} ${day}`;
  }

  if (dtstart) {
    const d = new Date(dtstart + "T00:00:00");
    const label = d.toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
    text += ` · next due ${label}`;
  }

  return text;
}

////////////////////////////////////////////////////////////////////////
//
export function extractDtstart(raw: string): { dtstart: string | null; rrule: string } {
  const lines = raw.split("\n");
  let dtstart: string | null = null;
  const rest: string[] = [];
  for (const line of lines) {
    if (line.startsWith("DTSTART:")) {
      const iso = line.slice(8).replace(/(\d{4})(\d{2})(\d{2})T.*/, "$1-$2-$3");
      dtstart = iso;
    } else {
      rest.push(line);
    }
  }
  return { dtstart, rrule: rest.join("\n") };
}

export function combineDtstart(rrule: string, dateStr: string): string {
  const d = dateStr.replace(/-/g, "");
  return `DTSTART:${d}T000000Z\n${rrule}`;
}

////////////////////////////////////////////////////////////////////////
//
// Default RRULE for new budgets -- first of every month.
//
export const DEFAULT_RRULE = "RRULE:FREQ=MONTHLY;BYMONTHDAY=1";
