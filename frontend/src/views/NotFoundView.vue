<script setup lang="ts">
//
// NotFoundView — shown for any `/app/` path no route matches.  Public,
// so a mistyped link says so instead of bouncing through sign-in.
//
</script>

<template>
  <div
    class="flex min-h-screen items-center justify-center bg-canvas px-page-x"
  >
    <div
      class="w-full max-w-sm rounded-card border border-border bg-surface px-8 py-10 text-center shadow-raised"
    >
      <h1 class="mb-2 text-title font-semibold text-fg">Page not found</h1>
      <p class="mb-6 text-body-sm text-fg-muted">
        There is nothing at this address. It may have moved, or the link may be
        incomplete.
      </p>
      <router-link
        :to="{ name: 'overview' }"
        class="block w-full rounded-control bg-accent py-2.5 text-label text-fg-on-accent hover:bg-accent-hover"
      >
        Go to overview
      </router-link>
    </div>
  </div>
</template>
