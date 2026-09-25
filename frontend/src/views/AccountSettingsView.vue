<script setup lang="ts">
//
// AccountSettingsView — security and notification settings.
// (/app/account/settings/)  Route shell: each section is a
// self-contained feature component in `features/settings/`.
//
// Outgoing invitations are listed here as well as on each account's
// page, so a user who invited people to several accounts can review
// and cancel them in one place.  Each section loads once on mount.
//

// app imports
//
import ApiKeysSection from "@/features/settings/ApiKeysSection.vue";
import NotificationsSection from "@/features/settings/NotificationsSection.vue";
import OutgoingInvitationsSection from "@/features/settings/OutgoingInvitationsSection.vue";
import PasswordSection from "@/features/settings/PasswordSection.vue";
import AppShell from "@/features/shell/AppShell.vue";
</script>

<template>
  <AppShell>
    <div class="mx-auto max-w-lg py-4">
      <!-- ── Security ─────────────────────────────────────────────── -->
      <h1 class="mb-5 text-[22px] font-medium text-neutral-900">Security</h1>

      <PasswordSection />

      <ApiKeysSection />

      <NotificationsSection />

      <OutgoingInvitationsSection />
    </div>
  </AppShell>
</template>
