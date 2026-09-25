//
// The signed-in user.  Model layer: domain type and DTO mappers for
// `/api/v1/users/me/`.
//

// app imports
//
import type { UserDto, UserUpdateDto } from "@/api/dto";

////////////////////////////////////////////////////////////////////////
//
export interface User {
  username: string;
  email: string;
  name: string;
  defaultBankAccountId: string | null;
  // IANA zone used to show dates, e.g. `"America/Los_Angeles"`.
  timezone: string;
  // `false` for accounts created by invitation that have not set a
  // password yet; password and email changes are refused until then.
  hasUsablePassword: boolean;
}

export const DEFAULT_TIMEZONE = "UTC";

////////////////////////////////////////////////////////////////////////
//
export function userFromDto(dto: UserDto): User {
  return {
    username: dto.username,
    email: dto.email,
    name: dto.name ?? "",
    defaultBankAccountId: dto.default_bank_account ?? null,
    timezone: dto.timezone || DEFAULT_TIMEZONE,
    hasUsablePassword: dto.has_usable_password,
  };
}

////////////////////////////////////////////////////////////////////////
//
export type UserUpdate = Partial<Pick<User, "name" | "timezone" | "defaultBankAccountId">>;

export function userToUpdateDto(update: UserUpdate): UserUpdateDto {
  const dto: UserUpdateDto = {};
  if (update.name !== undefined) dto.name = update.name;
  if (update.timezone !== undefined) dto.timezone = update.timezone;
  if (update.defaultBankAccountId !== undefined) {
    dto.default_bank_account = update.defaultBankAccountId || null;
  }
  return dto;
}
