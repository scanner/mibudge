//
// Notification preference and channel preference API calls.
//

import { useAuthStore } from "@/stores/auth";
import type { ChannelPreference, NotificationPreference } from "@/types/api";

////////////////////////////////////////////////////////////////////////
//
export function getNotificationPreferences(): Promise<NotificationPreference[]> {
  return useAuthStore().request<NotificationPreference[]>("/notification-preferences/");
}

export function updateNotificationPreference(
  kind: string,
  enabled: boolean,
): Promise<NotificationPreference> {
  return useAuthStore().request<NotificationPreference>(
    `/notification-preferences/${encodeURIComponent(kind)}/`,
    { method: "PATCH", body: { enabled } as unknown as BodyInit },
  );
}

////////////////////////////////////////////////////////////////////////
//
export function getChannelPreferences(): Promise<ChannelPreference[]> {
  return useAuthStore().request<ChannelPreference[]>("/channel-preferences/");
}

export function updateChannelPreference(
  channel: string,
  digest_frequency: string,
): Promise<ChannelPreference> {
  return useAuthStore().request<ChannelPreference>(`/channel-preferences/${channel}/`, {
    method: "PATCH",
    body: { digest_frequency } as unknown as BodyInit,
  });
}
