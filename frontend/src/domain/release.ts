//
// The release the SPA was built from, and whether the server runs a
// different one.  Domain layer.
//
// The SPA and the server are released together, so a server on another
// release means this tab runs an old (or, after a rollback, a newer)
// bundle and a page load gets the matching one.  `"unknown"` on either
// side (a build not given a version) never counts as different.
//

////////////////////////////////////////////////////////////////////////
//
export const UNKNOWN_VERSION = "unknown";

export const SPA_VERSION: string = __MIBUDGE_SPA_VERSION__;

////////////////////////////////////////////////////////////////////////
//
export function isOtherRelease(
  serverVersion: string | null,
  spaVersion: string = SPA_VERSION,
): boolean {
  return (
    serverVersion !== null &&
    serverVersion !== UNKNOWN_VERSION &&
    spaVersion !== UNKNOWN_VERSION &&
    serverVersion !== spaVersion
  );
}
