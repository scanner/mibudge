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
const { email, password, submitting, errorMessage, submit: onSubmit } = useLogin();
</script>

<template>
  <div class="flex min-h-screen items-center justify-center bg-neutral-50 px-4">
    <form
      class="w-full max-w-sm rounded-card border border-neutral-200 bg-white p-6 shadow-sm"
      @submit.prevent="onSubmit"
    >
      <h1 class="text-xl font-medium text-neutral-900">Sign in to mibudge</h1>
      <p class="mt-1 text-sm text-neutral-500">Your budget dashboard awaits.</p>

      <label class="mt-5 block text-sm font-medium text-neutral-700">
        Email
        <input
          v-model="email"
          type="email"
          autocomplete="email"
          required
          class="mt-1 w-full rounded-subcard border-neutral-200 bg-white text-sm focus:border-ocean-400 focus:ring-ocean-400"
        />
      </label>

      <label class="mt-4 block text-sm font-medium text-neutral-700">
        Password
        <input
          v-model="password"
          type="password"
          autocomplete="current-password"
          required
          class="mt-1 w-full rounded-subcard border-neutral-200 bg-white text-sm focus:border-ocean-400 focus:ring-ocean-400"
        />
      </label>

      <div class="mt-1 flex justify-end">
        <a href="/accounts/password/reset/" class="text-xs text-neutral-500 hover:text-ocean-500"
          >Forgot password?</a
        >
      </div>

      <p v-if="errorMessage" class="mt-3 text-sm text-coral-600" role="alert">
        {{ errorMessage }}
      </p>

      <button
        type="submit"
        :disabled="submitting || !email || !password"
        class="mt-5 w-full rounded-full bg-ocean-400 px-4 py-2 text-sm font-medium text-white hover:bg-ocean-600 disabled:cursor-not-allowed disabled:bg-neutral-300"
      >
        {{ submitting ? "Signing in…" : "Sign in" }}
      </button>
    </form>
  </div>
</template>
