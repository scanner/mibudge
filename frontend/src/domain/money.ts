//
// Money -- an exact decimal amount in one currency.  Domain layer:
// pure TypeScript, no Vue, Pinia, router or API imports.
//
// `Money` wraps a `decimal.js` `Decimal` so arithmetic on amounts is
// exact (no binary floating point).  The REST API sends amounts as
// decimal strings (`"142.80"`) with a sibling `*_currency` field; the
// model layer turns each pair into a `Money` with `Money.of(...)`, and
// turns it back into a decimal string with `toDecimalString()`.
//
// `formatMoney` is the single currency formatter for the SPA; the
// `MoneyAmount` component and every inline amount go through it.
//

// 3rd party imports
//
import Decimal from "decimal.js";

////////////////////////////////////////////////////////////////////////
//
export const DEFAULT_CURRENCY = "USD";

////////////////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////
//
export class Money {
  readonly amount: Decimal;
  readonly currency: string;

  private constructor(amount: Decimal, currency: string) {
    this.amount = amount;
    this.currency = currency || DEFAULT_CURRENCY;
  }

  ////////////////////////////////////////////////////////////////////
  //
  // Build from an API decimal string (or a `Decimal` / integer).  An
  // unparseable or missing value is zero, so a malformed field renders
  // as `$0.00` instead of throwing inside a template.
  //
  static of(
    amount: string | number | Decimal | null | undefined,
    currency: string | null | undefined = DEFAULT_CURRENCY,
  ): Money {
    return new Money(toDecimal(amount) ?? new Decimal(0), currency ?? DEFAULT_CURRENCY);
  }

  static zero(currency: string = DEFAULT_CURRENCY): Money {
    return new Money(new Decimal(0), currency);
  }

  ////////////////////////////////////////////////////////////////////
  //
  // Build from a nullable API field: `null` stays `null`, so an absent
  // target or funding amount stays distinguishable from zero.
  //
  static ofNullable(
    amount: string | null | undefined,
    currency: string | null | undefined = DEFAULT_CURRENCY,
  ): Money | null {
    if (amount === null || amount === undefined || amount === "") return null;
    return Money.of(amount, currency);
  }

  ////////////////////////////////////////////////////////////////////
  //
  plus(other: Money | Decimal | string): Money {
    return new Money(this.amount.plus(operand(other)), this.currency);
  }

  minus(other: Money | Decimal | string): Money {
    return new Money(this.amount.minus(operand(other)), this.currency);
  }

  abs(): Money {
    return new Money(this.amount.abs(), this.currency);
  }

  negated(): Money {
    return new Money(this.amount.negated(), this.currency);
  }

  ////////////////////////////////////////////////////////////////////
  //
  isZero(): boolean {
    return this.amount.isZero();
  }

  isNegative(): boolean {
    return this.amount.isNegative() && !this.amount.isZero();
  }

  isPositive(): boolean {
    return this.amount.isPositive() && !this.amount.isZero();
  }

  cmp(other: Money | Decimal | string): number {
    return this.amount.comparedTo(operand(other));
  }

  equals(other: Money | Decimal | string): boolean {
    return this.cmp(other) === 0;
  }

  ////////////////////////////////////////////////////////////////////
  //
  // Two-decimal string for the REST API, e.g. `"-12.30"`.
  //
  toDecimalString(): string {
    return this.amount.toFixed(2);
  }

  toString(): string {
    return `${this.toDecimalString()} ${this.currency}`;
  }
}

////////////////////////////////////////////////////////////////////////
//
function operand(value: Money | Decimal | string): Decimal {
  if (value instanceof Money) return value.amount;
  return value instanceof Decimal ? value : new Decimal(value);
}

////////////////////////////////////////////////////////////////////////
//
// Parse a decimal string or number to a `Decimal`, or `null` when it is
// not a finite number.  Used for amounts typed by the user, e.g.
// `toDecimal("12.5")` → `12.5`, `toDecimal("abc")` → `null`.
//
export function toDecimal(value: string | number | Decimal | null | undefined): Decimal | null {
  if (value === null || value === undefined) return null;
  if (value instanceof Decimal) return value;
  if (typeof value === "string" && value.trim() === "") return null;
  try {
    const d = new Decimal(typeof value === "string" ? value.trim() : value);
    return d.isFinite() ? d : null;
  } catch {
    return null;
  }
}

////////////////////////////////////////////////////////////////////////
//
// Sum a list of `Money` values in one currency.
//
export function sumMoney(values: Money[], currency: string = DEFAULT_CURRENCY): Money {
  return values.reduce((sum, m) => sum.plus(m), Money.zero(values[0]?.currency ?? currency));
}

////////////////////////////////////////////////////////////////////////
//
export interface FormatMoneyOptions {
  // BCP 47 locale; `undefined` uses the browser's default locale.
  locale?: string;
  // `"always"` prefixes a `+` on positive amounts.
  signDisplay?: "auto" | "always";
}

////////////////////////////////////////////////////////////////////////
//
// Format as a localised currency string, e.g. `$1,234.50` or
// `-$12.00`.  The `Decimal` is converted to a `Number` only here, for
// `Intl.NumberFormat`; two-decimal amounts below 2^53 / 100 format
// exactly.
//
export function formatMoney(money: Money, options: FormatMoneyOptions = {}): string {
  return new Intl.NumberFormat(options.locale, {
    style: "currency",
    currency: money.currency || DEFAULT_CURRENCY,
    signDisplay: options.signDisplay ?? "auto",
  }).format(money.amount.toNumber());
}
