//
// Current user lookup and profile update.
//

import { useAuthStore } from "@/stores/auth";
import type { User } from "@/types/api";

////////////////////////////////////////////////////////////////////////
//
export function getCurrentUser(): Promise<User> {
  return useAuthStore().request<User>("/users/me/");
}

////////////////////////////////////////////////////////////////////////
//
export function updateCurrentUser(body: Partial<User>): Promise<User> {
  return useAuthStore().request<User>("/users/me/", {
    method: "PATCH",
    body: body as BodyInit,
  });
}

////////////////////////////////////////////////////////////////////////
//
export interface ChangePasswordPayload {
  current_password: string;
  new_password: string;
  confirm_password: string;
}

export function changePassword(payload: ChangePasswordPayload): Promise<void> {
  return useAuthStore().request<void>("/users/me/change-password/", {
    method: "POST",
    body: payload as unknown as BodyInit,
  });
}
