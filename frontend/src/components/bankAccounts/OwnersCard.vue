<script setup lang="ts">
//
// OwnersCard — the account's owners and the inline "invite co-owner"
// email form.  Presentational: the email is a `v-model`; emits `open`,
// `review` (validate and ask to confirm) and `close`.
//

////////////////////////////////////////////////////////////////////////
//
defineProps<{
  owners: string[];
  formOpen: boolean;
  sending: boolean;
  sent: boolean;
  error: string | null;
}>();

const email = defineModel<string>("email", { required: true });

const emit = defineEmits<{
  (e: "open"): void;
  (e: "review"): void;
  (e: "close"): void;
}>();
</script>

<template>
  <!-- Owners + invite form
       The invite form lives inside this section so it visually belongs
       with the owners list.  The two-step flow (enter email → confirm
       in ConfirmSheet) keeps the destructive-action confirmation
       pattern consistent with the delete flow below. -->
  <section class="overflow-hidden rounded-card border border-border bg-surface">
    <div
      class="flex items-center justify-between border-b border-border-subtle px-4 py-3"
    >
      <h2
        class="text-[11px] font-semibold uppercase tracking-wider text-fg-muted"
      >
        Owners
      </h2>
      <button
        v-if="!formOpen"
        type="button"
        class="text-xs font-medium text-fg-link hover:text-accent-hover"
        @click="emit('open')"
      >
        + Invite co-owner
      </button>
    </div>

    <!-- Current owners list -->
    <ul class="divide-y divide-border-subtle">
      <li
        v-for="owner in owners"
        :key="owner"
        class="px-4 py-3 text-sm text-fg"
      >
        {{ owner }}
      </li>
      <li v-if="!owners.length" class="px-4 py-3 text-sm text-fg-subtle">—</li>
    </ul>

    <!-- Inline invite form — step 1: enter the email address.
         Appears below the owner list when inviteOpen is true.
         The "Review" button triggers client-side validation and then
         opens the ConfirmSheet for step 2 rather than sending directly,
         giving the user a chance to double-check the address. -->
    <div v-if="formOpen" class="border-t border-border-subtle px-4 py-4">
      <label
        class="mb-1.5 block text-sm font-medium text-fg"
        for="invite-email"
      >
        Email address to invite
      </label>
      <input
        id="invite-email"
        v-model="email"
        type="email"
        autocomplete="email"
        placeholder="colleague@example.com"
        class="w-full rounded-subcard border border-border-strong px-3 py-2.5 text-sm text-fg focus:border-border-focus focus:outline-none focus:ring-1 focus:ring-border-focus"
        @keydown.enter="emit('review')"
        @keydown.escape="emit('close')"
      />
      <p v-if="error" class="mt-1 text-xs text-danger-fg">{{ error }}</p>
      <div class="mt-3 flex gap-2">
        <button
          type="button"
          :disabled="sending"
          class="flex-1 rounded-subcard bg-accent py-2 text-sm font-medium text-fg-on-accent hover:bg-accent-hover disabled:opacity-50"
          @click="emit('review')"
        >
          {{ sending ? "Sending…" : "Review" }}
        </button>
        <button
          type="button"
          class="flex-1 rounded-subcard border border-border py-2 text-sm font-medium text-fg hover:bg-surface-sunken"
          @click="emit('close')"
        >
          Cancel
        </button>
      </div>
    </div>

    <!-- Success banner shown after a successful invite send.
         Displayed inside the Owners card so it is contextually near
         the action that triggered it. -->
    <div
      v-if="sent && !formOpen"
      class="border-t border-border-subtle px-4 py-3 text-sm text-success-fg"
    >
      Invitation sent.
    </div>
  </section>
</template>
