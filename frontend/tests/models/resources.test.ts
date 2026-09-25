//
// Mapper tests for the smaller models: user, bank, bank account and
// funding, category, invitation, API key, notification preferences,
// and pages.
//

// 3rd party imports
//
import { describe, expect, it } from "vitest";

// app imports
//
import { Money } from "@/domain/money";
import {
  apiKeyFromDto,
  apiKeyToCreateDto,
  createdApiKeyFromDto,
} from "@/models/apiKey";
import { bankFromDto } from "@/models/bank";
import {
  bankAccountFromDto,
  bankAccountToCreateDto,
  bankAccountToUpdateDto,
  fundingRunIsNoop,
  fundingRunResultFromDto,
  fundingSummaryFromDto,
} from "@/models/bankAccount";
import { invitationFromDto } from "@/models/invitation";
import {
  channelPreferenceFromDto,
  notificationPreferenceFromDto,
} from "@/models/notification";
import { pageFromDto } from "@/models/page";
import { transactionCategoryFromDto } from "@/models/transactionCategory";
import { userFromDto, userToUpdateDto } from "@/models/user";
import {
  makeApiKey,
  makeBank,
  makeBankAccount,
  makeCategory,
  makeChannelPreference,
  makeFundingRunResult,
  makeFundingSummary,
  makeInvitation,
  makeNotificationPreference,
  makePage,
  makeUser,
} from "../mocks/factories";

////////////////////////////////////////////////////////////////////////
//
describe("user", () => {
  // GIVEN: the current user as the API sends it
  // WHEN:  it is mapped, and a profile edit is turned into a PATCH
  // THEN:  fields are camel-cased, a missing timezone is UTC, and an
  //        empty default account is sent as null
  //
  it("maps both ways", () => {
    const user = userFromDto(
      makeUser({ username: "ada", timezone: "", has_usable_password: false }),
    );
    expect(user.username).toBe("ada");
    expect(user.timezone).toBe("UTC");
    expect(user.hasUsablePassword).toBe(false);
    expect(userToUpdateDto({ name: "Ada", defaultBankAccountId: "" })).toEqual({
      name: "Ada",
      default_bank_account: null,
    });
    expect(userToUpdateDto({ timezone: "Asia/Tokyo" })).toEqual({
      timezone: "Asia/Tokyo",
    });
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("bank and bank account", () => {
  // GIVEN: a bank and a bank account as the API sends them
  // WHEN:  they are mapped
  // THEN:  balances are Money and dates are typed
  //
  it("maps from the API", () => {
    expect(
      bankFromDto(makeBank({ name: "BofA", routing_number: null }))
        .routingNumber,
    ).toBeNull();
    const account = bankAccountFromDto(
      makeBankAccount({
        posted_balance: "10.5",
        available_balance: "9.25",
        unallocated_budget: null,
        last_posted_through: "2026-09-01",
      }),
    );
    expect(account.postedBalance.toDecimalString()).toBe("10.50");
    expect(account.availableBalance.toDecimalString()).toBe("9.25");
    expect(account.unallocatedBudgetId).toBeNull();
    expect(account.lastPostedThrough).toBe("2026-09-01");
  });

  // GIVEN: a new account and an edit
  // WHEN:  they become request bodies
  // THEN:  opening balances are sent only when given, and a cleared
  //        account number is sent as null
  //
  it("maps to the API", () => {
    expect(
      bankAccountToCreateDto({
        accountType: "S",
        name: "Savings",
        bankId: "bank",
        currency: "USD",
        accountNumber: "123",
        postedBalance: Money.of("100"),
        availableBalance: null,
      }),
    ).toEqual({
      account_type: "S",
      name: "Savings",
      bank: "bank",
      currency: "USD",
      account_number: "123",
      posted_balance: "100.00",
    });
    expect(
      bankAccountToUpdateDto({ accountNumber: "", autoFundingEnabled: false }),
    ).toEqual({
      account_number: null,
      auto_funding_enabled: false,
    });
  });

  // GIVEN: a funding summary and funding-run results
  // WHEN:  they are mapped
  // THEN:  totals are Money, next dates are calendar dates, and a run
  //        that did and reported nothing is a no-op
  //
  it("maps funding summaries and runs", () => {
    const summary = fundingSummaryFromDto(
      makeFundingSummary({
        total_amount: "55.00",
        schedules: [
          {
            schedule: "RRULE:FREQ=MONTHLY",
            next_date: "2026-10-01",
            total_amount: "55.00",
            currency: "USD",
            budget_count: 2,
          },
        ],
      }),
    );
    expect(summary.total.toDecimalString()).toBe("55.00");
    expect(summary.schedules[0]).toMatchObject({
      nextDate: "2026-10-01",
      budgetCount: 2,
    });
    expect(
      fundingRunIsNoop(fundingRunResultFromDto(makeFundingRunResult())),
    ).toBe(true);
    const run = fundingRunResultFromDto(
      makeFundingRunResult({ skipped_budgets: ["Rent"] }),
    );
    expect(run.skippedBudgets).toEqual(["Rent"]);
    expect(fundingRunIsNoop(run)).toBe(false);
  });
});

////////////////////////////////////////////////////////////////////////
//
describe("categories, invitations, API keys, notifications, pages", () => {
  // GIVEN: DTOs for the remaining resources
  // WHEN:  they are mapped
  // THEN:  fields are camel-cased and schema-non-null owners that come
  //        back null stay null
  //
  it("maps from the API", () => {
    expect(transactionCategoryFromDto(makeCategory()).ownerId).toBeNull();
    expect(
      transactionCategoryFromDto(makeCategory({ owner: "u1" })).ownerId,
    ).toBe("u1");

    const inv = invitationFromDto(
      makeInvitation({ invitee_email: "x@example.com" }),
    );
    expect(inv.inviteeEmail).toBe("x@example.com");

    const key = apiKeyFromDto(
      makeApiKey({ revoked_at: "2026-09-02T00:00:00Z" }),
    );
    expect(key.revokedAt).toBe("2026-09-02T00:00:00Z");
    expect(
      createdApiKeyFromDto({ ...makeApiKey(), key: "mb_secret" }).plaintext,
    ).toBe("mb_secret");
    expect(apiKeyToCreateDto("importer", null)).toEqual({
      name: "importer",
      expiry_days: null,
    });

    expect(
      notificationPreferenceFromDto(makeNotificationPreference()).canSuppress,
    ).toBe(true);
    expect(
      channelPreferenceFromDto(makeChannelPreference()).digestFrequency,
    ).toBe("daily_evening");

    const page = pageFromDto(makePage([1, 2]), (n: number) => n * 10);
    expect(page).toEqual({ count: 2, next: null, results: [10, 20] });
  });
});
