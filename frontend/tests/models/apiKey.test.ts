//
// API key model tests (`src/models/apiKey.ts`): which keys still
// authenticate.
//

// 3rd party imports
//
import { describe, expect, it } from "vitest";

// app imports
//
import { apiKeyFromDto, isApiKeyActive } from "@/models/apiKey";
import { makeApiKey } from "../mocks/factories";

const NOW = new Date("2026-09-30T12:00:00Z");

////////////////////////////////////////////////////////////////////////
//
describe("isApiKeyActive", () => {
  // GIVEN: an API key that is revoked, expired, or neither
  // WHEN:  it is checked against a fixed "now"
  // THEN:  only a key that is unrevoked and not past its expiry is active
  //
  it.each([
    ["never expires", {}, true],
    ["expires later", { expires_at: "2026-10-30T12:00:00Z" }, true],
    ["expired", { expires_at: "2026-09-29T12:00:00Z" }, false],
    ["revoked", { revoked_at: "2026-09-29T12:00:00Z" }, false],
  ])("%s", (_label, overrides, active) => {
    expect(isApiKeyActive(apiKeyFromDto(makeApiKey(overrides)), NOW)).toBe(
      active,
    );
  });
});
