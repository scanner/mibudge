//
// A financial institution.  Model layer: domain type and DTO mapper for
// `/api/v1/banks/`.
//

// app imports
//
import type { BankDto } from "@/api/dto";

////////////////////////////////////////////////////////////////////////
//
export interface Bank {
  id: string;
  name: string;
  routingNumber: string | null;
  defaultCurrency: string;
}

export function bankFromDto(dto: BankDto): Bank {
  return {
    id: dto.id,
    name: dto.name,
    routingNumber: dto.routing_number ?? null,
    defaultCurrency: dto.default_currency,
  };
}
