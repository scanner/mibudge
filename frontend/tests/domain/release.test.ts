//
// Release tests (`src/domain/release.ts`): when the server's release
// is outside the range the SPA supports.
//

// 3rd party imports
//
import { describe, expect, it } from "vitest";

// app imports
//
import {
  isUnsupportedServer,
  SPA_VERSION,
  SUPPORTED_SERVER,
} from "@/domain/release";

////////////////////////////////////////////////////////////////////////
//
describe("isUnsupportedServer", () => {
  // GIVEN: the release the server reports and the range the SPA supports
  // WHEN:  they are compared
  // THEN:  only a semver release outside a semver range is unsupported;
  //        a server that has not reported yet, or "unknown" on either
  //        side, never is
  //
  it.each([
    [null, ">=0.5.2 <0.7.0", false],
    ["0.6.1", ">=0.5.2 <0.7.0", false],
    ["0.7.0-rc.1", ">=0.5.2 <0.7.0", false],
    ["0.5.1", ">=0.5.2 <0.7.0", true],
    ["0.7.0", ">=0.5.2 <0.7.0", true],
    ["unknown", ">=0.5.2 <0.7.0", false],
    ["0.6.1", "unknown", false],
  ])("server %j, supported %j", (server, supported, expected) => {
    expect(isUnsupportedServer(server, supported)).toBe(expected);
  });

  // GIVEN: the release and range the test build defines
  // WHEN:  no range is passed
  // THEN:  the comparison uses the built-in range
  //
  it("defaults to the built-in range", () => {
    expect(SPA_VERSION).toBe("1.0.0");
    expect(SUPPORTED_SERVER).toBe(">=1.0.0 <2.0.0");
    expect(isUnsupportedServer("1.5.0")).toBe(false);
    expect(isUnsupportedServer("2.0.0")).toBe(true);
  });
});
