//
// `useFormErrors`: turn a failed request into per-field and form-level
// messages.  Composables layer.
//
// A DRF 400 answers `{"field": ["message"], "non_field_errors": [...]}`;
// `setError(err, { inlineFields })` puts the field messages under their
// field names and the rest in `formError`.  `inlineFields` names the
// fields the form shows a message beside; a message for any other field
// becomes `formError`, so a 400 is never silent.  A form that shows no
// per-field messages omits it.  Any other failure becomes `formError`
// via `describeError`, or a message given per HTTP status (e.g. a 409).
//

// 3rd party imports
//
import { computed, ref } from "vue";
import type { ComputedRef } from "vue";

// app imports
//
import { ApiError, describeError } from "@/api/errors";

////////////////////////////////////////////////////////////////////////
//
export interface SetErrorOptions {
  // Used when the error carries no message of its own.
  fallback?: string;
  // A fixed message per HTTP status, e.g. `{ 409: "Already exists." }`.
  statusMessages?: Record<number, string>;
  // The fields the form shows a message beside.  Default: none.
  inlineFields?: readonly string[];
}

export interface UseFormErrors {
  fieldErrors: ComputedRef<Record<string, string[]>>;
  formError: ComputedRef<string | null>;
  fieldError: (field: string) => string | null;
  setError: (err: unknown, options?: SetErrorOptions) => void;
  setFormError: (message: string | null) => void;
  clear: () => void;
}

////////////////////////////////////////////////////////////////////////
//
export function useFormErrors(): UseFormErrors {
  const fieldErrors = ref<Record<string, string[]>>({});
  const formError = ref<string | null>(null);

  function fieldError(field: string): string | null {
    return fieldErrors.value[field]?.[0] ?? null;
  }

  function setError(err: unknown, options: SetErrorOptions = {}): void {
    fieldErrors.value = {};
    formError.value = null;
    if (err instanceof ApiError) {
      const fixed = options.statusMessages?.[err.status];
      if (fixed) {
        formError.value = fixed;
        return;
      }
      if (err.status === 400) {
        const shown = new Set(options.inlineFields ?? []);
        const unshown = Object.entries(err.fieldErrors).find(
          ([field]) => !shown.has(field),
        );
        fieldErrors.value = err.fieldErrors;
        formError.value =
          err.nonFieldErrors[0] ?? err.detail ?? unshown?.[1][0] ?? null;
        if (!formError.value && Object.keys(err.fieldErrors).length === 0) {
          formError.value = options.fallback ?? err.message;
        }
        return;
      }
    }
    formError.value = describeError(err, options.fallback);
  }

  function setFormError(message: string | null): void {
    formError.value = message;
  }

  function clear(): void {
    fieldErrors.value = {};
    formError.value = null;
  }

  return {
    fieldErrors: computed(() => fieldErrors.value),
    formError: computed(() => formError.value),
    fieldError,
    setError,
    setFormError,
    clear,
  };
}
