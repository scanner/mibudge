//
// Notification preferences per kind, and per-channel digest settings.
// API layer.
//
// Both list endpoints answer a plain JSON array; the schema describes
// them as paginated (a drf-spectacular annotation gap).
//

// app imports
//
import type {
  ChannelPreferenceDto,
  DeliveryModeDto,
  DigestFrequencyDto,
  NotificationPreferenceDto,
} from "@/api/dto";
import type { HttpClient } from "@/api/http";
import { V1 } from "./paths";

////////////////////////////////////////////////////////////////////////
//
export function notificationsResource(http: HttpClient) {
  return {
    listPreferences(): Promise<NotificationPreferenceDto[]> {
      return http.get(`${V1}/notification-preferences/`);
    },

    // Kinds may contain dots (`users.password_changed`), so the path
    // segment is URI-encoded.
    //
    updatePreference(kind: string, deliveryMode: DeliveryModeDto) {
      return http.patch<NotificationPreferenceDto>(
        `${V1}/notification-preferences/${encodeURIComponent(kind)}/`,
        { delivery_mode: deliveryMode },
      );
    },

    listChannels(): Promise<ChannelPreferenceDto[]> {
      return http.get(`${V1}/channel-preferences/`);
    },

    updateChannel(channel: string, digestFrequency: DigestFrequencyDto) {
      return http.patch<ChannelPreferenceDto>(
        `${V1}/channel-preferences/${channel}/`,
        {
          digest_frequency: digestFrequency,
        },
      );
    },
  };
}
