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
// The page ends with the releases of the SPA and the server.
//

// app imports
//
import ApiKeysSection from "@/features/settings/ApiKeysSection.vue";
import NotificationsSection from "@/features/settings/NotificationsSection.vue";
import OutgoingInvitationsSection from "@/features/settings/OutgoingInvitationsSection.vue";
import PasswordSection from "@/features/settings/PasswordSection.vue";
import VersionSection from "@/features/settings/VersionSection.vue";
import AppShell from "@/features/shell/AppShell.vue";
import BasePageHeader from "@/components/base/BasePageHeader.vue";
</script>

<template>
  <AppShell>
    <div class="mx-auto max-w-lg py-4">
      <!-- ── Security ─────────────────────────────────────────────── -->
      <BasePageHeader title="Security" />

      <PasswordSection />

      <ApiKeysSection />

      <NotificationsSection />

      <OutgoingInvitationsSection />

      <VersionSection />
    </div>
  </AppShell>
</template>
