//
// The release the SPA was built from, the server releases it supports,
// and whether the server's release is one of them.  Domain layer.
//
// `SUPPORTED_SERVER` is a semver range (`>=0.5.2 <0.7.0`).  While the
// SPA is released with the server it is exactly the build's release
// (`vite.config.ts`), so a server on another release means this tab
// runs an old (or, after a rollback, a newer) bundle, and a page load
// gets the matching one.  A server release or a range that is not
// semver (`"unknown"`, from a build not given a version) never counts
// as unsupported.
//

// 3rd party imports
//
import { satisfies, valid, validRange } from "semver";

////////////////////////////////////////////////////////////////////////
//
export const SPA_VERSION: string = __MIBUDGE_SPA_VERSION__;

export const SUPPORTED_SERVER: string = __MIBUDGE_SUPPORTED_SERVER__;

////////////////////////////////////////////////////////////////////////
//
export function isUnsupportedServer(
  serverVersion: string | null,
  supported: string = SUPPORTED_SERVER,
): boolean {
  if (serverVersion === null || !valid(serverVersion)) return false;
  if (!validRange(supported)) return false;
  return !satisfies(serverVersion, supported, { includePrerelease: true });
}
