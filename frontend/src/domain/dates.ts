//
// Calendar dates and instants for display.  Domain layer: pure
// TypeScript; the timezone, the clock ("now") and the locale are
// parameters, never read from globals behind the caller's back.
//
// Two kinds of value come from the API:
//
// - Date-only fields (`target_date`, `next_recurrence`,
//   `next_funding.date`, ...) are calendar dates, `"YYYY-MM-DD"`.  The
//   model layer carries them as `LocalDate`, a branded string.  They
//   have no timezone: formatting renders the same calendar day in every
//   browser and profile zone.
// - Instants (`transaction_date`, `created_at`, ...) are ISO datetimes.
//   The calendar date of an instant depends on the zone; helpers here
//   take the profile timezone (`user.timezone`) explicitly.
//
// BofA transactions are date-only values the importer stores as
// midnight in the user's zone (e.g. `2024-10-15T07:00:00Z` for midnight
// PDT), so `txDateStr(iso, profileZone)` recovers the bank's date.
//

////////////////////////////////////////////////////////////////////////
//
// A calendar date, `"YYYY-MM-DD"`.  The brand keeps arbitrary strings
// (and ISO datetimes) out of date-only APIs; build one with
// `toLocalDate()`.  Lexical order is chronological order.
//
export type LocalDate = string & { readonly __brand: "LocalDate" };

const LOCAL_DATE_RE = /^(\d{4})-(\d{2})-(\d{2})$/;

////////////////////////////////////////////////////////////////////////
//
// Validate a `"YYYY-MM-DD"` string as a `LocalDate`; anything else
// (including `null`, `""` and datetimes) is `null`.
//
export function toLocalDate(value: string | null | undefined): LocalDate | null {
  if (!value) return null;
  const m = LOCAL_DATE_RE.exec(value);
  if (!m) return null;
  const [y, mo, d] = [Number(m[1]), Number(m[2]), Number(m[3])];
  const probe = new Date(Date.UTC(y, mo - 1, d));
  if (probe.getUTCMonth() !== mo - 1 || probe.getUTCDate() !== d) return null;
  return value as LocalDate;
}

////////////////////////////////////////////////////////////////////////
//
// The calendar date as UTC midnight.  Internal anchor for arithmetic
// and formatting: pairing UTC midnight with `timeZone: "UTC"` renders
// the same calendar day whatever the browser zone is.
//
function utcMidnight(date: LocalDate): Date {
  const [y, m, d] = date.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d));
}

function fromUtcMidnight(d: Date): LocalDate {
  return d.toISOString().slice(0, 10) as LocalDate;
}

////////////////////////////////////////////////////////////////////////
//
// Parse a date-only string (`"2026-08-01"`) as browser-local midnight,
// for code that needs a `Date` (e.g. a date picker).
// `new Date("2026-08-01")` parses as UTC midnight, which is the
// previous day in zones west of UTC.
//
export function parseLocalDate(s: string): Date {
  const [y, m, d] = s.split("-").map(Number);
  return new Date(y, m - 1, d);
}

////////////////////////////////////////////////////////////////////////
//
// Today's date in `timezone`, e.g. `todayDateStr("Asia/Tokyo")`.
// `now` defaults to the current instant.
//
export function todayDateStr(timezone: string, now: Date = new Date()): LocalDate {
  return new Intl.DateTimeFormat("sv-SE", { timeZone: timezone }).format(now) as LocalDate;
}

////////////////////////////////////////////////////////////////////////
//
// The calendar date of an instant (ISO datetime) in `timezone`.
//
export function txDateStr(isoString: string, timezone: string): LocalDate {
  return new Intl.DateTimeFormat("sv-SE", { timeZone: timezone }).format(
    new Date(isoString),
  ) as LocalDate;
}

////////////////////////////////////////////////////////////////////////
//
// `date` shifted by `days` calendar days (negative for the past).
//
export function addDays(date: LocalDate, days: number): LocalDate {
  const d = utcMidnight(date);
  d.setUTCDate(d.getUTCDate() + days);
  return fromUtcMidnight(d);
}

////////////////////////////////////////////////////////////////////////
//
// Whole calendar days from `from` to `to` (negative when `to` is
// earlier).  Independent of DST: both ends are UTC midnights.
//
export function daysBetween(from: LocalDate, to: LocalDate): number {
  const ms = utcMidnight(to).getTime() - utcMidnight(from).getTime();
  return Math.round(ms / 86_400_000);
}

////////////////////////////////////////////////////////////////////////
//
// Format a calendar date, e.g.
// `formatLocalDate(d, { month: "short", day: "numeric" })` → `"Aug 1"`.
// The same day is rendered in every browser zone.
//
export function formatLocalDate(
  date: LocalDate,
  options: Intl.DateTimeFormatOptions,
  locale?: string,
): string {
  return utcMidnight(date).toLocaleDateString(locale, { ...options, timeZone: "UTC" });
}

////////////////////////////////////////////////////////////////////////
//
// Format the date part of an instant, e.g. an account's `created_at`.
// `timezone` defaults to the browser's zone.
//
export function formatInstantDate(
  isoString: string,
  options: Intl.DateTimeFormatOptions,
  timezone?: string,
  locale?: string,
): string {
  return new Date(isoString).toLocaleDateString(locale, {
    ...options,
    ...(timezone ? { timeZone: timezone } : {}),
  });
}

////////////////////////////////////////////////////////////////////////
//
// List-group header for a calendar date: `"Today"`, `"Yesterday"`, a
// short date (`"Apr 15"`), or a short date with the year when the year
// differs from today's (`"Dec 25, 2025"`).  `todayStr` comes from
// `todayDateStr(profileZone)`, so "today" follows the profile zone.
//
export function formatDateHeader(dateStr: string, todayStr: string, locale?: string): string {
  const date = toLocalDate(dateStr);
  const today = toLocalDate(todayStr);
  if (!date || !today) return dateStr;
  if (date === today) return "Today";
  if (date === addDays(today, -1)) return "Yesterday";

  const differentYear = date.slice(0, 4) !== today.slice(0, 4);
  return formatLocalDate(
    date,
    { month: "short", day: "numeric", ...(differentYear ? { year: "numeric" } : {}) },
    locale,
  );
}

////////////////////////////////////////////////////////////////////////
//
// Long form of a transaction instant in `timezone`, e.g.
// `"Tuesday, October 15, 2024"`, with `" at 2:34 PM"` appended when
// the local time is not midnight.
//
export function formatTxDateLong(isoString: string, timezone: string, locale?: string): string {
  const d = new Date(isoString);

  const timeParts = new Intl.DateTimeFormat("en-US", {
    timeZone: timezone,
    hour: "numeric",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(d);

  const hour = parseInt(timeParts.find((p) => p.type === "hour")?.value ?? "0");
  const minute = parseInt(timeParts.find((p) => p.type === "minute")?.value ?? "0");

  const datePart = new Intl.DateTimeFormat(locale, {
    timeZone: timezone,
    weekday: "long",
    month: "long",
    day: "numeric",
    year: "numeric",
  }).format(d);

  // `hour12: false` renders midnight as "24" in some engines.
  if ((hour === 0 || hour === 24) && minute === 0) return datePart;

  const timePart = new Intl.DateTimeFormat(locale, {
    timeZone: timezone,
    hour: "numeric",
    minute: "2-digit",
  }).format(d);

  return `${datePart} at ${timePart}`;
}
