<script setup lang="ts">
//
// EmailChangeErrorView — shown when a confirm or revoke link cannot be
// processed.  The `reason` query parameter is set by the Django view.
//
// This is a public route (no auth required).
//
import { computed } from "vue";
import { useRoute } from "vue-router";

const route = useRoute();

const MESSAGES: Record<string, string> = {
  expired:
    "The verification link has expired. Verification links are valid for 24 hours — please request a new email change from your account profile.",
  already_confirmed:
    "This verification link has already been used. If you expected to see a success page, your email address was already updated.",
  revoked:
    "This link is no longer valid — the email change request was cancelled.",
  email_taken:
    "The requested email address has been registered by another account. Please request a new email change and choose a different address.",
  already_revoked: "This cancellation link has already been used.",
  window_closed:
    "The 7-day cancellation window has closed. The email address change is now permanent. Contact support if you need assistance.",
  invalid:
    "This link is not valid. It may have already been used or the URL may be incomplete.",
};

const FALLBACK =
  "Something went wrong processing your request. Please try again or contact support.";

const message = computed(() => {
  const reason = route.query.reason as string | undefined;
  return reason ? (MESSAGES[reason] ?? FALLBACK) : FALLBACK;
});
</script>

<template>
  <div class="flex min-h-screen items-center justify-center bg-canvas px-4">
    <div
      class="w-full max-w-sm rounded-card border border-border bg-surface px-8 py-10 text-center shadow-sm"
    >
      <div class="mb-4 flex justify-center">
        <span
          class="flex h-12 w-12 items-center justify-center rounded-full bg-danger-bg text-2xl text-danger-fg"
        >
          !
        </span>
      </div>
      <h1 class="mb-2 text-[18px] font-semibold text-fg">
        Unable to process link
      </h1>
      <p class="mb-6 text-sm text-fg-muted">{{ message }}</p>
      <a
        href="/app/login/"
        class="block w-full rounded-subcard bg-accent py-2.5 text-sm font-medium text-fg-on-accent hover:bg-accent-hover"
      >
        Sign in
      </a>
    </div>
  </div>
</template>
