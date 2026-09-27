<script setup lang="ts">
//
// LoginView — email + password sign-in.  (Public route.)  Route shell
// over `useLogin`: on success the user lands on the route named in
// `?next=`, or the overview.
//

// app imports
//
import { useLogin } from "@/features/auth/useLogin";

////////////////////////////////////////////////////////////////////////
//
const {
  email,
  password,
  submitting,
  errorMessage,
  submit: onSubmit,
} = useLogin();
</script>

<template>
  <div class="flex min-h-screen items-center justify-center bg-canvas px-4">
    <form
      class="w-full max-w-sm rounded-card border border-border bg-surface p-6 shadow-sm"
      @submit.prevent="onSubmit"
    >
      <h1 class="text-xl font-medium text-fg">Sign in to mibudge</h1>
      <p class="mt-1 text-sm text-fg-muted">Your budget dashboard awaits.</p>

      <label class="mt-5 block text-sm font-medium text-fg">
        Email
        <input
          v-model="email"
          type="email"
          autocomplete="email"
          required
          class="mt-1 w-full rounded-subcard border-border-strong bg-surface text-sm focus:border-border-focus focus:ring-border-focus"
        />
      </label>

      <label class="mt-4 block text-sm font-medium text-fg">
        Password
        <input
          v-model="password"
          type="password"
          autocomplete="current-password"
          required
          class="mt-1 w-full rounded-subcard border-border-strong bg-surface text-sm focus:border-border-focus focus:ring-border-focus"
        />
      </label>

      <div class="mt-1 flex justify-end">
        <a
          href="/accounts/password/reset/"
          class="text-xs text-fg-muted hover:text-accent-fg"
          >Forgot password?</a
        >
      </div>

      <p v-if="errorMessage" class="mt-3 text-sm text-danger-fg" role="alert">
        {{ errorMessage }}
      </p>

      <button
        type="submit"
        :disabled="submitting || !email || !password"
        class="mt-5 w-full rounded-full bg-accent px-4 py-2 text-sm font-medium text-fg-on-accent hover:bg-accent-hover disabled:cursor-not-allowed disabled:bg-surface-strong"
      >
        {{ submitting ? "Signing in…" : "Sign in" }}
      </button>
    </form>
  </div>
</template>
