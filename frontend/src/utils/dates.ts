// Date utilities for transaction display.
//
// Transactions from BofA are date-only values stored as midnight in the
// user's local timezone (e.g. "2024-10-15T07:00:00Z" for midnight PDT).
// All display helpers accept an IANA timezone string so they render the
// correct calendar date regardless of the browser's local timezone.

////////////////////////////////////////////////////////////////////////
//
// Return today's date as a YYYY-MM-DD string in the given timezone.
//
export function todayDateStr(timezone: string): string {
  return new Intl.DateTimeFormat("sv-SE", { timeZone: timezone }).format(new Date());
}

////////////////////////////////////////////////////////////////////////
//
// Extract the YYYY-MM-DD date string from an ISO datetime in the given
// timezone.
//
export function txDateStr(isoString: string, timezone: string): string {
  return new Intl.DateTimeFormat("sv-SE", { timeZone: timezone }).format(new Date(isoString));
}

////////////////////////////////////////////////////////////////////////
//
// Format a YYYY-MM-DD date string as a relative label ("Today",
// "Yesterday") or a short date ("Apr 15").  Pass today's date string
// (from todayDateStr) to avoid recomputing it on every call.
//
export function formatDateHeader(dateStr: string, todayStr: string, timezone: string): string {
  const yesterday = new Date(todayStr + "T00:00:00");
  yesterday.setDate(yesterday.getDate() - 1);
  const yesterdayStr = yesterday.toLocaleDateString("sv-SE");

  if (dateStr === todayStr) return "Today";
  if (dateStr === yesterdayStr) return "Yesterday";

  // Parse as local midnight so toLocaleDateString uses the right date.
  const d = new Date(dateStr + "T00:00:00");
  return d.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    timeZone: timezone,
  });
}

////////////////////////////////////////////////////////////////////////
//
// Format a transaction ISO datetime string as a long date for the
// detail view, e.g. "Tuesday, October 15, 2024".  If the time in the
// user's timezone is non-midnight, appends " at 2:34 PM".
//
export function formatTxDateLong(isoString: string, timezone: string): string {
  const d = new Date(isoString);

  const timeParts = new Intl.DateTimeFormat("en-US", {
    timeZone: timezone,
    hour: "numeric",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(d);

  const hour = parseInt(timeParts.find((p) => p.type === "hour")?.value ?? "0");
  const minute = parseInt(timeParts.find((p) => p.type === "minute")?.value ?? "0");

  const datePart = new Intl.DateTimeFormat(undefined, {
    timeZone: timezone,
    weekday: "long",
    month: "long",
    day: "numeric",
    year: "numeric",
  }).format(d);

  if (hour === 0 && minute === 0) return datePart;

  const timePart = new Intl.DateTimeFormat(undefined, {
    timeZone: timezone,
    hour: "numeric",
    minute: "2-digit",
  }).format(d);

  return `${datePart} at ${timePart}`;
}
