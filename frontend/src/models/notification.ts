//
// Notification preferences.  Model layer: domain types and DTO mappers
// for `/api/v1/notification-preferences/` and
// `/api/v1/channel-preferences/`.
//

// app imports
//
import type {
  ChannelPreferenceDto,
  DeliveryModeDto,
  DigestFrequencyDto,
  NotificationPreferenceDto,
} from "@/api/dto";

////////////////////////////////////////////////////////////////////////
//
export type DeliveryMode = DeliveryModeDto;
export type DigestFrequency = DigestFrequencyDto;

////////////////////////////////////////////////////////////////////////
//
export interface NotificationPreference {
  kind: string;
  displayName: string;
  // `false` for notifications that cannot be turned off.
  canSuppress: boolean;
  deliveryMode: DeliveryMode;
}

export function notificationPreferenceFromDto(
  dto: NotificationPreferenceDto,
): NotificationPreference {
  return {
    kind: dto.kind,
    displayName: dto.display_name,
    canSuppress: dto.can_suppress,
    deliveryMode: dto.delivery_mode,
  };
}

////////////////////////////////////////////////////////////////////////
//
export interface ChannelPreference {
  channel: string;
  displayName: string;
  digestFrequency: DigestFrequency;
}

export function channelPreferenceFromDto(
  dto: ChannelPreferenceDto,
): ChannelPreference {
  return {
    channel: dto.channel,
    displayName: dto.display_name,
    digestFrequency: dto.digest_frequency,
  };
}
