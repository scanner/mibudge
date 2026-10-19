//
// Release tests (`src/domain/release.ts`): when the server's release
// counts as other than the SPA's.
//

// 3rd party imports
//
import { describe, expect, it } from "vitest";

// app imports
//
import { isOtherRelease, SPA_VERSION } from "@/domain/release";

////////////////////////////////////////////////////////////////////////
//
describe("isOtherRelease", () => {
  // GIVEN: the release the server reports and the SPA's own
  // WHEN:  they are compared
  // THEN:  only two known, different releases count as other; a server
  //        that has not reported yet, or "unknown" on either side, never
  //        does
  //
  it.each([
    [null, "1.0.0", false],
    ["1.0.0", "1.0.0", false],
    ["1.1.0", "1.0.0", true],
    ["unknown", "1.0.0", false],
    ["1.1.0", "unknown", false],
  ])("server %j, SPA %j", (server, spa, expected) => {
    expect(isOtherRelease(server, spa)).toBe(expected);
  });

  // GIVEN: the release the test build defines
  // WHEN:  no SPA release is passed
  // THEN:  the comparison uses the built-in one
  //
  it("defaults to the built-in release", () => {
    expect(SPA_VERSION).toBe("1.0.0");
    expect(isOtherRelease("1.0.0")).toBe(false);
  });
});
