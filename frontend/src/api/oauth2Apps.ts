//
// OAuth2 application management (/api/v1/users/me/oauth2-apps/).
//
// These are apps the user has *registered* (to be granted delegated
// access to their own or others' accounts), not apps they have
// authorized.  See docs/authentication.md for the registration policy:
// the client secret is shown in plaintext exactly once, at creation, and
// only for confidential clients.
//
// The endpoint keys on `client_id` (django-oauth-toolkit's lookup field),
// not a UUID like the rest of the API.
//

import { useAuthStore } from "@/stores/auth";
import type {
  OAuth2Application,
  OAuth2ApplicationCreated,
  OAuth2ClientType,
  Paginated,
} from "@/types/api";

////////////////////////////////////////////////////////////////////////
//
export function listOAuth2Apps(): Promise<Paginated<OAuth2Application>> {
  return useAuthStore().request<Paginated<OAuth2Application>>("/users/me/oauth2-apps/");
}

////////////////////////////////////////////////////////////////////////
//
// clientType is create-only — it cannot be changed after registration.
//
export function registerOAuth2App(
  name: string,
  clientType: OAuth2ClientType,
  redirectUris: string[],
): Promise<OAuth2ApplicationCreated> {
  return useAuthStore().request<OAuth2ApplicationCreated>("/users/me/oauth2-apps/", {
    method: "POST",
    body: {
      name,
      client_type: clientType,
      redirect_uris: redirectUris,
    } as unknown as BodyInit,
  });
}

////////////////////////////////////////////////////////////////////////
//
// Only name and redirect URIs are editable; client_type is create-only,
// so this sends a PATCH with just the mutable fields.  The viewset
// re-serializes the response with the read serializer, so the returned
// object is a full OAuth2Application.
//
export function updateOAuth2App(
  clientId: string,
  fields: { name?: string; redirect_uris?: string[] },
): Promise<OAuth2Application> {
  return useAuthStore().request<OAuth2Application>(`/users/me/oauth2-apps/${clientId}/`, {
    method: "PATCH",
    body: fields as unknown as BodyInit,
  });
}

////////////////////////////////////////////////////////////////////////
//
// Deregistering deletes every grant, access token and refresh token
// issued for the app; any user who authorized it loses access at once.
//
export function deregisterOAuth2App(clientId: string): Promise<void> {
  return useAuthStore().request<void>(`/users/me/oauth2-apps/${clientId}/`, {
    method: "DELETE",
  });
}
