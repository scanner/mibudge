<script setup lang="ts">
//
// EmailChangeRevokedView — shown after a 'this wasn't me' revocation link
// is clicked and the email change is successfully cancelled.
//
// This is a public route (no auth required) because the user arrives from
// their email client, potentially without an active session.
//

// app imports
//
import BaseButton from "@/components/base/BaseButton.vue";
import BaseCard from "@/components/base/BaseCard.vue";
</script>

<template>
  <div
    class="flex min-h-screen items-center justify-center bg-canvas px-page-x"
  >
    <BaseCard class="w-full max-w-sm px-8 py-10 text-center shadow-raised">
      <div class="mb-4 flex justify-center">
        <span
          class="flex h-12 w-12 items-center justify-center rounded-pill bg-warning-bg text-page-title text-warning-fg"
        >
          ✕
        </span>
      </div>
      <h1 class="mb-2 text-title font-semibold text-fg">
        Email change cancelled
      </h1>
      <p class="mb-6 text-body-sm text-fg-muted">
        The email address change on your account has been cancelled. Your
        original address is still active.
      </p>
      <p class="mb-6 text-meta text-fg-subtle">
        If the change had already been confirmed, your email address has been
        restored and all active sessions have been signed out. A security notice
        was sent to both addresses.
      </p>
      <BaseButton as="a" href="/app/login/" block> Sign in </BaseButton>
    </BaseCard>
  </div>
</template>
