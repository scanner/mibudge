//
// How the SPA displays dates, times, numbers and money.  Domain layer.
//
// `DISPLAY_FORMAT` is the one declaration every formatter reads: the
// date formatters in `domain/dates.ts` and `formatMoney` in
// `domain/money.ts` take it as a defaulted last argument, so call sites
// name only *what* they show (a `DateForm`) and never *how*.  Changing
// a field here changes every rendered date, time or amount; a user's
// display preference, when there is one, supplies this object.
//

////////////////////////////////////////////////////////////////////////
//
export interface DisplayFormat {
  // BCP 47 locale for words, digits and separators; `undefined` uses
  // the browser's locale.
  locale: string | undefined;
  // `words`: "Jul 17, 2026".  `iso`: "2026-07-17", which sorts
  // lexically and reads the same everywhere.
  dates: "words" | "iso";
  // `locale`: the locale's own clock.  `12h`: "2:34 PM".  `24h`:
  // "14:34".
  clock: "locale" | "12h" | "24h";
}

export const DISPLAY_FORMAT: Readonly<DisplayFormat> = Object.freeze({
  locale: undefined,
  dates: "words",
  clock: "locale",
});

////////////////////////////////////////////////////////////////////////
//
// The shapes a date is shown in.  With `dates: "iso"` every form that
// includes a day renders as `YYYY-MM-DD` and `month-year` as `YYYY-MM`.
//
//   month-day   "Sep 30"                        -- within the year
//   date        "Jul 17, 2026"                  -- a full calendar date
//   month-year  "Aug 2026"                      -- a goal's target month
//   full        "Tuesday, October 15, 2024"     -- a transaction's
//               (", 2:34 PM" when not midnight)    detail heading
//
export type DateForm = "month-day" | "date" | "month-year" | "full";
