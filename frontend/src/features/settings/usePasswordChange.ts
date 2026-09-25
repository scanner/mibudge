//
// `usePasswordChange`: the change-password form.  Feature composable
// (settings).
//
// Submitting is allowed once the new password scores at least "fair"
// (2 of 4) on the strength meter.  A 400 puts DRF's messages under the
// matching fields; any other failure is a form-level message.
//

// 3rd party imports
//
import { computed, ref } from "vue";

// app imports
//
import { api } from "@/api";
import { useFormErrors } from "@/composables/useFormErrors";

////////////////////////////////////////////////////////////////////////
//
export const MIN_PASSWORD_SCORE = 2;

////////////////////////////////////////////////////////////////////////
//
export function usePasswordChange() {
  const currentPassword = ref("");
  const newPassword = ref("");
  const confirmPassword = ref("");
  const strengthScore = ref<number | null>(null);
  const saving = ref(false);
  const success = ref(false);
  const errors = useFormErrors();

  const submitDisabled = computed(
    () =>
      saving.value ||
      strengthScore.value === null ||
      strengthScore.value < MIN_PASSWORD_SCORE,
  );

  async function submit(): Promise<void> {
    saving.value = true;
    success.value = false;
    errors.clear();
    try {
      await api.users.changePassword({
        current_password: currentPassword.value,
        new_password: newPassword.value,
        confirm_password: confirmPassword.value,
      });
      success.value = true;
      currentPassword.value = "";
      newPassword.value = "";
      confirmPassword.value = "";
      strengthScore.value = null;
    } catch (err) {
      errors.setError(err, {
        fallback: "Failed to change password.",
        inlineFields: ["current_password", "new_password", "confirm_password"],
      });
    } finally {
      saving.value = false;
    }
  }

  return {
    currentPassword,
    newPassword,
    confirmPassword,
    strengthScore,
    saving,
    success,
    submitDisabled,
    fieldError: errors.fieldError,
    formError: errors.formError,
    submit,
  };
}
