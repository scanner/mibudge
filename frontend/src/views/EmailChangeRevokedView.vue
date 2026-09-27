<script setup lang="ts">
//
// EmailChangeRevokedView — shown after a 'this wasn't me' revocation link
// is clicked and the email change is successfully cancelled.
//
// This is a public route (no auth required) because the user arrives from
// their email client, potentially without an active session.
//
</script>

<template>
  <div class="flex min-h-screen items-center justify-center bg-canvas px-4">
    <div
      class="w-full max-w-sm rounded-card border border-border bg-surface px-8 py-10 text-center shadow-sm"
    >
      <div class="mb-4 flex justify-center">
        <span
          class="flex h-12 w-12 items-center justify-center rounded-full bg-warning-bg text-2xl text-warning-fg"
        >
          ✕
        </span>
      </div>
      <h1 class="mb-2 text-[18px] font-semibold text-fg">
        Email change cancelled
      </h1>
      <p class="mb-6 text-sm text-fg-muted">
        The email address change on your account has been cancelled. Your
        original address is still active.
      </p>
      <p class="mb-6 text-xs text-fg-subtle">
        If the change had already been confirmed, your email address has been
        restored and all active sessions have been signed out. A security notice
        was sent to both addresses.
      </p>
      <a
        href="/app/login/"
        class="block w-full rounded-subcard bg-accent py-2.5 text-sm font-medium text-fg-on-accent hover:bg-accent-hover"
      >
        Sign in
      </a>
    </div>
  </div>
</template>
