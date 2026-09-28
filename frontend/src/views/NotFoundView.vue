<script setup lang="ts">
//
// NotFoundView — shown for any `/app/` path no route matches.  Public,
// so a mistyped link says so instead of bouncing through sign-in.
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
      <h1 class="mb-2 text-title font-semibold text-fg">Page not found</h1>
      <p class="mb-6 text-body-sm text-fg-muted">
        There is nothing at this address. It may have moved, or the link may be
        incomplete.
      </p>
      <BaseButton as="RouterLink" :to="{ name: 'overview' }" block>
        Go to overview
      </BaseButton>
    </BaseCard>
  </div>
</template>
