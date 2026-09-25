//
// API keys (machine credentials).  Model layer: domain type and DTO
// mappers for `/api/v1/users/me/api-keys/`.
//

// app imports
//
import type { ApiKeyCreateDto, ApiKeyCreatedDto, ApiKeyDto } from "@/api/dto";

////////////////////////////////////////////////////////////////////////
//
export interface ApiKey {
  id: string;
  name: string;
  // First characters of the key, shown so the user can tell keys apart.
  prefix: string;
  expiresAt: string | null;
  lastUsedAt: string | null;
  revokedAt: string | null;
  createdAt: string;
}

// The create response: the key plus its plaintext, shown exactly once.
export interface CreatedApiKey extends ApiKey {
  plaintext: string;
}

////////////////////////////////////////////////////////////////////////
//
export function apiKeyFromDto(dto: ApiKeyDto): ApiKey {
  return {
    id: dto.uuid,
    name: dto.name,
    prefix: dto.prefix,
    expiresAt: dto.expires_at ?? null,
    lastUsedAt: dto.last_used_at ?? null,
    revokedAt: dto.revoked_at ?? null,
    createdAt: dto.created_at,
  };
}

export function createdApiKeyFromDto(dto: ApiKeyCreatedDto): CreatedApiKey {
  return { ...apiKeyFromDto(dto), plaintext: dto.key };
}

////////////////////////////////////////////////////////////////////////
//
// `expiryDays: null` creates a key that never expires.
//
export function apiKeyToCreateDto(name: string, expiryDays: number | null): ApiKeyCreateDto {
  return { name, expiry_days: expiryDays };
}
