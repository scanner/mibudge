<script setup lang="ts">
//
// EmailChangeConfirmedView — shown after the new-address verification link
// is clicked and the email change is successfully applied.
//
// This is a public route (no auth required) because the user may arrive
// directly from their email client.
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
          class="flex h-12 w-12 items-center justify-center rounded-pill bg-success-bg text-page-title text-success-fg"
        >
          ✓
        </span>
      </div>
      <h1 class="mb-2 text-title font-semibold text-fg">
        Email address updated
      </h1>
      <p class="mb-6 text-body-sm text-fg-muted">
        Your login email has been changed. Use your new address the next time
        you sign in.
      </p>
      <p class="mb-6 text-meta text-fg-subtle">
        If you didn't request this change, check your old inbox — a security
        notice with a cancellation link was sent there and remains valid for 7
        days.
      </p>
      <BaseButton as="a" href="/app/login/" block> Sign in </BaseButton>
    </BaseCard>
  </div>
</template>
