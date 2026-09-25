//
// `useProfileForm`: edit the user's name and timezone, and request an
// email change.  Feature composable (settings).
//
// Saving the profile updates the session's user, so dates everywhere
// switch to the new timezone.  The email change sends a verification
// link to the new address and a revocation link to the old one.
//

// 3rd party imports
//
import { ref } from "vue";

// app imports
//
import { api } from "@/api";
import { useFormErrors } from "@/composables/useFormErrors";
import { useSessionStore } from "@/stores/session";

////////////////////////////////////////////////////////////////////////
//
// Common IANA timezones.  The server validates the choice on save.
//
export const TIMEZONE_OPTIONS: { value: string; label: string }[] = [
  { value: "America/New_York", label: "Eastern Time — New York" },
  { value: "America/Chicago", label: "Central Time — Chicago" },
  { value: "America/Denver", label: "Mountain Time — Denver" },
  { value: "America/Phoenix", label: "Mountain Time (no DST) — Phoenix" },
  { value: "America/Los_Angeles", label: "Pacific Time — Los Angeles" },
  { value: "America/Anchorage", label: "Alaska Time — Anchorage" },
  { value: "Pacific/Honolulu", label: "Hawaii Time — Honolulu" },
  { value: "America/Puerto_Rico", label: "Atlantic Time — Puerto Rico" },
  { value: "Europe/London", label: "GMT/BST — London" },
  { value: "Europe/Paris", label: "Central European Time — Paris" },
  { value: "Europe/Berlin", label: "Central European Time — Berlin" },
  { value: "Europe/Athens", label: "Eastern European Time — Athens" },
  { value: "Asia/Dubai", label: "Gulf Standard Time — Dubai" },
  { value: "Asia/Kolkata", label: "India Standard Time — Kolkata" },
  { value: "Asia/Bangkok", label: "Indochina Time — Bangkok" },
  { value: "Asia/Shanghai", label: "China Standard Time — Shanghai" },
  { value: "Asia/Tokyo", label: "Japan Standard Time — Tokyo" },
  { value: "Australia/Sydney", label: "AEST/AEDT — Sydney" },
  { value: "Pacific/Auckland", label: "NZST/NZDT — Auckland" },
  { value: "UTC", label: "UTC" },
];

////////////////////////////////////////////////////////////////////////
//
export function useProfileForm() {
  const session = useSessionStore();

  const name = ref(session.user?.name ?? "");
  const timezone = ref(session.user?.timezone ?? "America/Los_Angeles");
  const saving = ref(false);
  const profileErrors = useFormErrors();

  // Resolves `true` once saved.
  //
  async function save(): Promise<boolean> {
    saving.value = true;
    profileErrors.clear();
    try {
      await session.updateProfile({
        name: name.value,
        timezone: timezone.value,
      });
      return true;
    } catch (err) {
      profileErrors.setError(err, { fallback: "Failed to save profile." });
      return false;
    } finally {
      saving.value = false;
    }
  }

  ////////////////////////////////////////////////////////////////////
  //
  const newEmail = ref("");
  const emailSaving = ref(false);
  const emailSuccess = ref(false);
  const emailErrors = useFormErrors();

  async function requestEmailChange(): Promise<void> {
    emailSaving.value = true;
    emailSuccess.value = false;
    emailErrors.clear();
    try {
      await api.users.changeEmail(newEmail.value);
      emailSuccess.value = true;
      newEmail.value = "";
    } catch (err) {
      emailErrors.setError(err, {
        fallback: "Failed to request email change.",
        statusMessages: {
          409: "That address is already in use, or an email change is already in progress. Please wait and try again.",
        },
      });
    } finally {
      emailSaving.value = false;
    }
  }

  return {
    name,
    timezone,
    saving,
    error: profileErrors.formError,
    save,
    newEmail,
    emailSaving,
    emailSuccess,
    emailError: emailErrors.formError,
    requestEmailChange,
  };
}
