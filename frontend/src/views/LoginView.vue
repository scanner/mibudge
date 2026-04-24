<script setup lang="ts">
//
// LoginView — username + password → POST /api/token/.  The backend
// sets the httpOnly refresh cookie on the response, so the auth store
// only needs to stash the access token in memory.
//
// Not behind the router auth guard (meta.public = true).  On success
// we redirect to the intended route (?next=) or to /app/.
//

// 3rd party imports
//
import { ref } from "vue";
import { useRoute, useRouter } from "vue-router";

// app imports
//
import { ApiError } from "@/api/client";
import { useAccountContextStore } from "@/stores/accountContext";
import { useAuthStore } from "@/stores/auth";

////////////////////////////////////////////////////////////////////////
//
const username = ref("");
const password = ref("");
const submitting = ref(false);
const errorMessage = ref<string | null>(null);

const auth = useAuthStore();
const ctx = useAccountContextStore();
const router = useRouter();
const route = useRoute();

////////////////////////////////////////////////////////////////////////
//
async function onSubmit() {
  errorMessage.value = null;
  submitting.value = true;
  try {
    await auth.login(username.value, password.value);
    // Warm the downstream stores so the shell's first render has data.
    await Promise.all([auth.loadUser(), ctx.init(true)]);
    const next = typeof route.query.next === "string" ? route.query.next : "/";
    router.replace(next);
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) {
      errorMessage.value = "Incorrect username or password.";
    } else {
      errorMessage.value = "Unable to sign in. Please try again.";
    }
  } finally {
    submitting.value = false;
  }
}
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
        Username
        <input
          v-model="username"
          type="text"
          autocomplete="username"
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

      <p v-if="errorMessage" class="mt-3 text-sm text-coral-600" role="alert">
        {{ errorMessage }}
      </p>

      <button
        type="submit"
        :disabled="submitting || !username || !password"
        class="mt-5 w-full rounded-full bg-ocean-400 px-4 py-2 text-sm font-medium text-white hover:bg-ocean-600 disabled:cursor-not-allowed disabled:bg-neutral-300"
      >
        {{ submitting ? "Signing in…" : "Sign in" }}
      </button>
    </form>
  </div>
</template>
