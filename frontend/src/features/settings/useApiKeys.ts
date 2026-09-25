//
// `useApiKeys`: list, create and revoke the user's API keys.  Feature
// composable (settings).
//
// A new key's plaintext is kept in `justCreated` until the user
// dismisses it; the server never returns it again.  Revoked and expired
// keys stay listed for audit, so revoking replaces the row instead of
// removing it.
//

// 3rd party imports
//
import { computed, onMounted, ref } from "vue";

// app imports
//
import { api } from "@/api";
import { describeError, isApiError } from "@/api/errors";
import { useFormErrors } from "@/composables/useFormErrors";
import type { ApiKey, CreatedApiKey } from "@/models/apiKey";
import {
  apiKeyFromDto,
  apiKeyToCreateDto,
  createdApiKeyFromDto,
} from "@/models/apiKey";

////////////////////////////////////////////////////////////////////////
//
export const EXPIRY_PRESETS: { value: string; label: string }[] = [
  { value: "30", label: "30 days" },
  { value: "60", label: "60 days" },
  { value: "90", label: "90 days" },
  { value: "365", label: "1 year" },
  { value: "custom", label: "Custom…" },
  { value: "never", label: "Never expires" },
];

////////////////////////////////////////////////////////////////////////
//
// The `expiry_days` value for a preset: a number of days, `null` for a
// key that never expires, or `undefined` when a custom value is not a
// positive number.
//
export function expiryDays(
  preset: string,
  customDays: string,
): number | null | undefined {
  if (preset === "never") return null;
  if (preset === "custom") {
    const days = Number(customDays);
    return Number.isFinite(days) && days > 0 ? days : undefined;
  }
  return Number(preset);
}

////////////////////////////////////////////////////////////////////////
//
export function useApiKeys() {
  const keys = ref<ApiKey[]>([]);
  const loading = ref(true);
  const error = ref<string | null>(null);
  const justCreated = ref<CreatedApiKey | null>(null);
  const copied = ref(false);

  const newKeyName = ref("");
  const newKeyExpiryPreset = ref("90");
  const newKeyCustomDays = ref("");
  const creating = ref(false);
  const createErrors = useFormErrors();

  const revokeTarget = ref<ApiKey | null>(null);
  const revokingId = ref<string | null>(null);

  ////////////////////////////////////////////////////////////////////
  //
  async function load(): Promise<void> {
    loading.value = true;
    error.value = null;
    try {
      const first = await api.apiKeys.list();
      keys.value = (await api.pages.all(first)).map(apiKeyFromDto);
    } catch (err) {
      error.value = describeError(err, "Failed to load API keys.");
    } finally {
      loading.value = false;
    }
  }

  onMounted(load);

  ////////////////////////////////////////////////////////////////////
  //
  async function create(): Promise<void> {
    createErrors.clear();
    const days = expiryDays(newKeyExpiryPreset.value, newKeyCustomDays.value);
    if (days === undefined) {
      createErrors.setFormError("Enter a valid number of days.");
      return;
    }
    creating.value = true;
    try {
      const dto = await api.apiKeys.create(
        apiKeyToCreateDto(newKeyName.value.trim(), days),
      );
      justCreated.value = createdApiKeyFromDto(dto);
      copied.value = false;
      newKeyName.value = "";
      newKeyExpiryPreset.value = "90";
      newKeyCustomDays.value = "";
      await load();
    } catch (err) {
      // The name is the only field a user can fix; show its message.
      const nameError = isApiError(err, 400)
        ? err.fieldErrors.name?.[0]
        : undefined;
      createErrors.setFormError(
        nameError ?? describeError(err, "Failed to create key."),
      );
    } finally {
      creating.value = false;
    }
  }

  async function copyNewKey(): Promise<void> {
    if (!justCreated.value) return;
    await navigator.clipboard.writeText(justCreated.value.plaintext);
    copied.value = true;
  }

  function dismissNewKey(): void {
    justCreated.value = null;
  }

  ////////////////////////////////////////////////////////////////////
  //
  async function revoke(key: ApiKey): Promise<void> {
    revokingId.value = key.id;
    try {
      const revoked = apiKeyFromDto(await api.apiKeys.revoke(key.id));
      keys.value = keys.value.map((k) => (k.id === key.id ? revoked : k));
    } catch (err) {
      error.value = describeError(err, "Failed to revoke API key.");
    } finally {
      revokingId.value = null;
      revokeTarget.value = null;
    }
  }

  return {
    keys,
    loading,
    error,
    justCreated,
    copied,
    newKeyName,
    newKeyExpiryPreset,
    newKeyCustomDays,
    creating,
    createError: computed(() => createErrors.formError.value),
    revokeTarget,
    revokingId,
    create,
    copyNewKey,
    dismissNewKey,
    revoke,
  };
}
