//
// `useNotificationPrefs`: per-kind delivery modes and the email digest
// frequency.  Feature composable (settings).
//
// A delivery-mode change applies at once and reverts if the server
// refuses it.
//

// 3rd party imports
//
import { onMounted, ref } from "vue";

// app imports
//
import { api } from "@/api";
import type { DeliveryMode, DigestFrequency, NotificationPreference } from "@/models/notification";
import { channelPreferenceFromDto, notificationPreferenceFromDto } from "@/models/notification";

////////////////////////////////////////////////////////////////////////
//
export const DIGEST_OPTIONS: { value: DigestFrequency; label: string }[] = [
  { value: "daily_morning", label: "Once daily (morning, ~7 am)" },
  { value: "daily_evening", label: "Once daily (evening, ~6 pm)" },
  { value: "twice_daily", label: "Twice daily (morning + evening)" },
  { value: "weekly_friday", label: "Weekly on Friday" },
  { value: "weekly_saturday", label: "Weekly on Saturday" },
  { value: "weekly_sunday", label: "Weekly on Sunday" },
];

export const DELIVERY_MODE_OPTIONS: { value: DeliveryMode; label: string }[] = [
  { value: "digest", label: "Digest" },
  { value: "immediate", label: "Immediate" },
  { value: "off", label: "Off" },
];

////////////////////////////////////////////////////////////////////////
//
export function useNotificationPrefs() {
  const prefs = ref<NotificationPreference[]>([]);
  const emailDigestFrequency = ref<DigestFrequency>("daily_evening");
  const loading = ref(true);
  const error = ref<string | null>(null);

  onMounted(async () => {
    try {
      const [kinds, channels] = await Promise.all([
        api.notifications.listPreferences(),
        api.notifications.listChannels(),
      ]);
      prefs.value = kinds.map(notificationPreferenceFromDto);
      const email = channels.map(channelPreferenceFromDto).find((c) => c.channel === "email");
      if (email) emailDigestFrequency.value = email.digestFrequency;
    } catch {
      error.value = "Failed to load notification preferences.";
    } finally {
      loading.value = false;
    }
  });

  async function setDeliveryMode(pref: NotificationPreference, mode: DeliveryMode) {
    const idx = prefs.value.findIndex((p) => p.kind === pref.kind);
    if (idx === -1) return;
    prefs.value[idx] = { ...pref, deliveryMode: mode };
    try {
      await api.notifications.updatePreference(pref.kind, mode);
    } catch {
      prefs.value[idx] = pref;
      error.value = "Failed to update notification preference.";
    }
  }

  async function saveEmailDigest(): Promise<void> {
    error.value = null;
    try {
      await api.notifications.updateChannel("email", emailDigestFrequency.value);
    } catch {
      error.value = "Failed to save email preference.";
    }
  }

  return { prefs, emailDigestFrequency, loading, error, setDeliveryMode, saveEmailDigest };
}
