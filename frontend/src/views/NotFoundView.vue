<script setup lang="ts">
//
// NotFoundView — shown for any `/app/` path no route matches.  Public,
// so a mistyped link says so instead of bouncing through sign-in.
//
</script>

<template>
  <div class="flex min-h-screen items-center justify-center bg-neutral-50 px-4">
    <div
      class="w-full max-w-sm rounded-card border border-neutral-200 bg-white px-8 py-10 text-center shadow-sm"
    >
      <h1 class="mb-2 text-[18px] font-semibold text-neutral-900">
        Page not found
      </h1>
      <p class="mb-6 text-sm text-neutral-500">
        There is nothing at this address. It may have moved, or the link may be
        incomplete.
      </p>
      <router-link
        :to="{ name: 'overview' }"
        class="block w-full rounded-subcard bg-ocean-400 py-2.5 text-sm font-medium text-white hover:bg-ocean-600"
      >
        Go to overview
      </router-link>
    </div>
  </div>
</template>
