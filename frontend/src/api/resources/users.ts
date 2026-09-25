//
// The current user (`/api/v1/users/me/...`).  API layer.
//

// app imports
//
import type { ChangePasswordDto, UserDto, UserUpdateDto } from "@/api/dto";
import type { HttpClient } from "@/api/http";
import { V1 } from "./paths";

////////////////////////////////////////////////////////////////////////
//
export function usersResource(http: HttpClient) {
  return {
    me(): Promise<UserDto> {
      return http.get(`${V1}/users/me/`);
    },

    updateMe(body: UserUpdateDto): Promise<UserDto> {
      return http.patch(`${V1}/users/me/`, body);
    },

    changePassword(body: ChangePasswordDto): Promise<null> {
      return http.post(`${V1}/users/me/change-password/`, body);
    },

    // Starts the email-change flow: a verification link goes to the new
    // address and a revocation link to the old one.
    //
    changeEmail(newEmail: string): Promise<null> {
      return http.post(`${V1}/users/me/change-email/`, { new_email: newEmail });
    },
  };
}
