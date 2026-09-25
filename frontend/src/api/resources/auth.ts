//
// JWT endpoints (`/api/token/...`).  API layer.
//
// Both requests go out without an access token and without the 401
// refresh: the refresh token is an httpOnly cookie the browser sends
// on its own, and a 401 here means the credentials or the cookie are
// no good.
//

// app imports
//
import type { AccessTokenDto } from "@/api/dto";
import type { HttpClient } from "@/api/http";
import { AUTH } from "./paths";

////////////////////////////////////////////////////////////////////////
//
export function authResource(http: HttpClient) {
  return {
    // Exchange email + password for an access token; the response also
    // sets the httpOnly refresh cookie.  Rejects with `ApiError(401)`
    // on bad credentials.
    //
    obtainToken(email: string, password: string): Promise<AccessTokenDto> {
      return http.request(`${AUTH}/token/`, {
        method: "POST",
        json: { email, password },
        auth: false,
      });
    },

    // Rotate the refresh cookie and get a new access token.
    //
    refreshToken(): Promise<AccessTokenDto> {
      return http.request(`${AUTH}/token/refresh/`, {
        method: "POST",
        auth: false,
      });
    },
  };
}
