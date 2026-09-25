//
// `useNotificationPrefs`: per-kind delivery modes and the email digest
// frequency.  Feature composable (settings).
//
// Both settings save as soon as they change and apply optimistically
// (`useOptimistic`): the new value shows at once, and a refused change
// shows the saved value again with the server's reason.
//

// 3rd party imports
//
import { computed, onMounted, ref } from "vue";

// app imports
//
import { api } from "@/api";
import { describeError } from "@/api/errors";
import { useOptimistic } from "@/composables/useOptimistic";
import type {
  DeliveryMode,
  DigestFrequency,
  NotificationPreference,
} from "@/models/notification";
import {
  channelPreferenceFromDto,
  notificationPreferenceFromDto,
} from "@/models/notification";

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
  // The server's email digest frequency.
  const savedDigest = ref<DigestFrequency>("daily_evening");
  const loading = ref(true);
  const loadError = ref<string | null>(null);

  onMounted(async () => {
    try {
      const [kinds, channels] = await Promise.all([
        api.notifications.listPreferences(),
        api.notifications.listChannels(),
      ]);
      prefs.value = kinds.map(notificationPreferenceFromDto);
      const email = channels
        .map(channelPreferenceFromDto)
        .find((c) => c.channel === "email");
      if (email) savedDigest.value = email.digestFrequency;
    } catch (err) {
      loadError.value = describeError(
        err,
        "Failed to load notification preferences.",
      );
    } finally {
      loading.value = false;
    }
  });

  ////////////////////////////////////////////////////////////////////
  //
  // Per-kind delivery mode, keyed by kind.  A saved change replaces the
  // kind's row with the server's answer.
  //
  const deliveryModes = useOptimistic(
    (kind: string) =>
      prefs.value.find((p) => p.kind === kind)?.deliveryMode ?? "off",
    async (kind: string, mode: DeliveryMode) => {
      const saved = notificationPreferenceFromDto(
        await api.notifications.updatePreference(kind, mode),
      );
      prefs.value = prefs.value.map((p) => (p.kind === kind ? saved : p));
    },
    { errorMessage: "Failed to update notification preference." },
  );

  function deliveryModeOf(pref: NotificationPreference): DeliveryMode {
    return deliveryModes.value(pref.kind);
  }

  function setDeliveryMode(
    pref: NotificationPreference,
    mode: DeliveryMode,
  ): Promise<void> {
    return deliveryModes.set(pref.kind, mode);
  }

  ////////////////////////////////////////////////////////////////////
  //
  // Email digest frequency (the only active channel).
  //
  const emailDigest = useOptimistic(
    (_channel: "email") => savedDigest.value,
    async (channel: "email", frequency: DigestFrequency) => {
      savedDigest.value = channelPreferenceFromDto(
        await api.notifications.updateChannel(channel, frequency),
      ).digestFrequency;
    },
    { errorMessage: "Failed to save email preference." },
  );
  const emailDigestFrequency = computed(() => emailDigest.value("email"));

  function setEmailDigest(frequency: DigestFrequency): Promise<void> {
    return emailDigest.set("email", frequency);
  }

  const error = computed(
    () =>
      loadError.value ?? deliveryModes.error.value ?? emailDigest.error.value,
  );

  return {
    prefs,
    emailDigestFrequency,
    loading,
    error,
    deliveryModeOf,
    setDeliveryMode,
    setEmailDigest,
  };
}
