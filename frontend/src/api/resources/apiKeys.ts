//
// API key management (`/api/v1/users/me/api-keys/`).  API layer.
//
// See docs/authentication.md for the security policy: a key's
// plaintext is returned exactly once, by `create`.
//

// app imports
//
import type {
  ApiKeyCreateDto,
  ApiKeyCreatedDto,
  ApiKeyDto,
  ApiKeyRevokeAllDto,
  Page,
} from "@/api/dto";
import type { HttpClient } from "@/api/http";
import { V1 } from "./paths";

////////////////////////////////////////////////////////////////////////
//
export function apiKeysResource(http: HttpClient) {
  return {
    list(): Promise<Page<ApiKeyDto>> {
      return http.get(`${V1}/users/me/api-keys/`);
    },

    create(body: ApiKeyCreateDto): Promise<ApiKeyCreatedDto> {
      return http.post(`${V1}/users/me/api-keys/`, body);
    },

    revoke(uuid: string): Promise<ApiKeyDto> {
      return http.post(`${V1}/users/me/api-keys/${uuid}/revoke/`);
    },

    // Revokes every active key; answers how many it revoked.
    revokeAll(): Promise<ApiKeyRevokeAllDto> {
      return http.post(`${V1}/users/me/api-keys/revoke-all/`);
    },
  };
}
