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
