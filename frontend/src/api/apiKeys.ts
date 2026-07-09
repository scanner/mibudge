//
// API key management (/api/v1/users/me/api-keys/).
//
// See docs/authentication.md for the security policy: keys are shown
// in plaintext exactly once, on creation.
//

import { useAuthStore } from "@/stores/auth";
import type { APIKey, APIKeyCreated, Paginated } from "@/types/api";

////////////////////////////////////////////////////////////////////////
//
export function listApiKeys(): Promise<Paginated<APIKey>> {
  return useAuthStore().request<Paginated<APIKey>>("/users/me/api-keys/");
}

////////////////////////////////////////////////////////////////////////
//
// expiryDays: number of days until expiry, or null for a key that
// never expires.
//
export function createApiKey(name: string, expiryDays: number | null): Promise<APIKeyCreated> {
  return useAuthStore().request<APIKeyCreated>("/users/me/api-keys/", {
    method: "POST",
    body: { name, expiry_days: expiryDays } as unknown as BodyInit,
  });
}

////////////////////////////////////////////////////////////////////////
//
export function revokeApiKey(uuid: string): Promise<APIKey> {
  return useAuthStore().request<APIKey>(`/users/me/api-keys/${uuid}/revoke/`, {
    method: "POST",
  });
}
