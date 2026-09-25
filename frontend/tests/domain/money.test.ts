//
// Money tests (`src/domain/money.ts`): construction from API strings,
// exact arithmetic, comparison, serialisation and formatting.
//

// 3rd party imports
//
import Decimal from "decimal.js";
import { describe, expect, it } from "vitest";

// app imports
//
import { formatMoney, Money, sumMoney, toDecimal } from "@/domain/money";

////////////////////////////////////////////////////////////////////////
//
describe("Money.of / ofNullable", () => {
  // GIVEN: a decimal string from the API, a number, or a missing value
  // WHEN:  it is turned into Money
  // THEN:  the amount is exact, the currency defaults to USD, and an
  //        unparseable value is zero
  //
  it.each([
    ["142.80", "USD", "142.80"],
    ["-0.1", "EUR", "-0.10"],
    [12, "USD", "12.00"],
    ["abc", "USD", "0.00"],
    [null, "USD", "0.00"],
  ] as const)("%j %s → %s", (amount, currency, expected) => {
    const m = Money.of(amount, currency);
    expect(m.toDecimalString()).toBe(expected);
    expect(m.currency).toBe(currency);
  });

  // GIVEN: no currency
  // WHEN:  Money is built
  // THEN:  it is in USD
  //
  it("defaults the currency", () => {
    expect(Money.of("1.00").currency).toBe("USD");
    expect(Money.of("1.00", "").currency).toBe("USD");
    expect(Money.of("1.00", null).currency).toBe("USD");
    expect(Money.zero().toString()).toBe("0.00 USD");
  });

  // GIVEN: a nullable API amount
  // WHEN:  it is converted
  // THEN:  null / empty stay null, anything else is Money
  //
  it.each([
    [null, null],
    [undefined, null],
    ["", null],
    ["5.00", "5.00"],
  ])("ofNullable(%j) → %j", (amount, expected) => {
    expect(Money.ofNullable(amount)?.toDecimalString() ?? null).toBe(expected);
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("arithmetic and comparison", () => {
  // GIVEN: amounts whose binary floating-point sum is inexact
  // WHEN:  they are added and subtracted as Money
  // THEN:  the result is exact
  //
  it("adds and subtracts exactly", () => {
    const sum = Money.of("0.1").plus("0.2");
    expect(sum.equals("0.3")).toBe(true);
    expect(sum.minus(Money.of("0.3")).isZero()).toBe(true);
    expect(Money.of("1").plus(new Decimal("2")).toDecimalString()).toBe("3.00");
  });

  // GIVEN: a positive, a negative and a zero amount
  // WHEN:  sign predicates, abs and negation are applied
  // THEN:  each reports its sign; zero is neither positive nor negative
  //
  it("reports signs", () => {
    const neg = Money.of("-12.34");
    expect(neg.isNegative()).toBe(true);
    expect(neg.isPositive()).toBe(false);
    expect(neg.abs().toDecimalString()).toBe("12.34");
    expect(neg.negated().toDecimalString()).toBe("12.34");
    const zero = Money.of("-0");
    expect([zero.isZero(), zero.isNegative(), zero.isPositive()]).toEqual([true, false, false]);
  });

  // GIVEN: two amounts
  // WHEN:  they are compared
  // THEN:  `cmp` orders them numerically
  //
  it("compares", () => {
    expect(Money.of("10").cmp("9.99")).toBe(1);
    expect(Money.of("10").cmp(Money.of("10.00"))).toBe(0);
    expect(Money.of("-1").cmp("0")).toBe(-1);
  });

  // GIVEN: a list of amounts, or none
  // WHEN:  they are summed
  // THEN:  the total is exact and keeps the currency
  //
  it("sums", () => {
    expect(sumMoney([Money.of("0.1", "EUR"), Money.of("0.2", "EUR")]).toString()).toBe("0.30 EUR");
    expect(sumMoney([]).toString()).toBe("0.00 USD");
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("toDecimal", () => {
  // GIVEN: user-typed input
  // WHEN:  it is parsed
  // THEN:  finite numbers parse; blanks, words and infinities are null
  //
  it.each([
    ["12.5", "12.5"],
    [" 7 ", "7"],
    [3, "3"],
    ["", null],
    ["   ", null],
    ["abc", null],
    ["Infinity", null],
    [null, null],
  ])("%j → %j", (input, expected) => {
    expect(toDecimal(input)?.toString() ?? null).toBe(expected);
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("formatMoney", () => {
  // GIVEN: an amount and a currency
  // WHEN:  it is formatted in the default (en-US) locale
  // THEN:  it is a currency string with two decimals and a leading minus
  //        for negatives, or a leading plus when the sign is forced
  //
  it.each([
    ["1234.5", "USD", "auto", "$1,234.50"],
    ["-12", "USD", "auto", "-$12.00"],
    ["12", "USD", "always", "+$12.00"],
    ["0", "EUR", "auto", "€0.00"],
  ] as const)("%s %s (%s) → %s", (amount, currency, signDisplay, expected) => {
    expect(formatMoney(Money.of(amount, currency), { signDisplay })).toBe(expected);
  });

  // GIVEN: an explicit locale
  // WHEN:  an amount is formatted
  // THEN:  the locale's separators are used
  //
  it("honours the locale", () => {
    expect(formatMoney(Money.of("1234.5", "EUR"), { locale: "de-DE" })).toBe("1.234,50\u00a0€");
  });
});
