<script setup lang="ts">
//
// LoginView — email + password sign-in.  (Public route.)  Route shell
// over `useLogin`: on success the user lands on the route named in
// `?next=`, or the overview.
//

// app imports
//
import { useLogin } from "@/features/auth/useLogin";
import BaseButton from "@/components/base/BaseButton.vue";
import BaseFormField from "@/components/base/BaseFormField.vue";
import BaseInput from "@/components/base/BaseInput.vue";
import BaseCard from "@/components/base/BaseCard.vue";

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
  <div
    class="flex min-h-screen items-center justify-center bg-canvas px-page-x"
  >
    <BaseCard
      as="form"
      class="w-full max-w-sm p-6 shadow-raised"
      @submit.prevent="onSubmit"
    >
      <h1 class="text-title text-fg">Sign in to mibudge</h1>
      <p class="mt-1 text-body-sm text-fg-muted">
        Your budget dashboard awaits.
      </p>

      <BaseFormField label="Email" class="mt-5">
        <template #default="{ id }">
          <BaseInput
            :id="id"
            v-model="email"
            type="email"
            autocomplete="email"
            required
          />
        </template>
      </BaseFormField>

      <BaseFormField label="Password" class="mt-4">
        <template #default="{ id }">
          <BaseInput
            :id="id"
            v-model="password"
            type="password"
            autocomplete="current-password"
            required
          />
        </template>
      </BaseFormField>

      <div class="mt-1 flex justify-end">
        <a
          href="/accounts/password/reset/"
          class="text-meta text-fg-muted hover:text-accent-fg"
          >Forgot password?</a
        >
      </div>

      <p
        v-if="errorMessage"
        class="mt-3 text-body-sm text-danger-fg"
        role="alert"
      >
        {{ errorMessage }}
      </p>

      <BaseButton
        type="submit"
        block
        :disabled="!email || !password"
        :loading="submitting"
        class="mt-5"
      >
        {{ submitting ? "Signing in…" : "Sign in" }}
      </BaseButton>
    </BaseCard>
  </div>
</template>
