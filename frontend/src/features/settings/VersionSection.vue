<script setup lang="ts">
//
// VersionSection -- the release this SPA bundle was built from and the
// release the server runs (from its `X-Mibudge-Version` header, via
// the release store).  The server's shows as a dash until a response
// has reported it.
//

// app imports
//
import { useReleaseStore } from "@/stores/release";

////////////////////////////////////////////////////////////////////////
//
const release = useReleaseStore();
</script>

<template>
  <p class="mt-10 text-center text-meta text-fg-muted">
    Web app {{ release.spaVersion }}, server
    {{ release.serverVersion ?? "-" }}
  </p>
</template>
