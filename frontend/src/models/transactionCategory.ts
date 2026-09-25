//
// Transaction categories.  Model layer: domain type and DTO mapper for
// `/api/v1/transaction-categories/`.
//

// app imports
//
import type { TransactionCategoryDto } from "@/api/dto";

////////////////////////////////////////////////////////////////////////
//
export interface TransactionCategory {
  id: string;
  group: string;
  name: string;
  // `"{group} : {name}"`, the category's stable identity.
  fullName: string;
  // `null` for the shared global base set.
  ownerId: string | null;
  archived: boolean;
}

export function transactionCategoryFromDto(
  dto: TransactionCategoryDto,
): TransactionCategory {
  return {
    id: dto.id,
    group: dto.group,
    name: dto.name,
    fullName: dto.full_name,
    // The schema marks this non-null; global rows come back `null`.
    ownerId: dto.owner ?? null,
    archived: dto.archived,
  };
}
