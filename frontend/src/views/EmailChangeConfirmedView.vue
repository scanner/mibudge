<script setup lang="ts">
//
// EmailChangeConfirmedView — shown after the new-address verification link
// is clicked and the email change is successfully applied.
//
// This is a public route (no auth required) because the user may arrive
// directly from their email client.
//
</script>

<template>
  <div class="flex min-h-screen items-center justify-center bg-canvas px-4">
    <div
      class="w-full max-w-sm rounded-card border border-border bg-surface px-8 py-10 text-center shadow-sm"
    >
      <div class="mb-4 flex justify-center">
        <span
          class="flex h-12 w-12 items-center justify-center rounded-full bg-success-bg text-2xl text-success-fg"
        >
          ✓
        </span>
      </div>
      <h1 class="mb-2 text-[18px] font-semibold text-fg">
        Email address updated
      </h1>
      <p class="mb-6 text-sm text-fg-muted">
        Your login email has been changed. Use your new address the next time
        you sign in.
      </p>
      <p class="mb-6 text-xs text-fg-subtle">
        If you didn't request this change, check your old inbox — a security
        notice with a cancellation link was sent there and remains valid for 7
        days.
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
