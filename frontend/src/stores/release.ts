//
// Release store: the release the server runs, as its responses report
// it.  Store layer.
//
// `createSessionHttpClient()` passes every response's
// `X-Mibudge-Version` to `noteServerVersion()`.  `updateAvailable` is
// true once the server reports a release other than the one this
// bundle was built from (`domain/release.ts`); the shell then offers a
// reload.
//

// 3rd party imports
//
import { defineStore } from "pinia";
import { computed, ref } from "vue";

// app imports
//
import { SPA_VERSION, isOtherRelease } from "@/domain/release";

////////////////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////
//
export const useReleaseStore = defineStore("release", () => {
  const serverVersion = ref<string | null>(null);
  const spaVersion = SPA_VERSION;

  const updateAvailable = computed(() =>
    isOtherRelease(serverVersion.value, spaVersion),
  );

  function noteServerVersion(version: string): void {
    serverVersion.value = version;
  }

  function reset(): void {
    serverVersion.value = null;
  }

  return {
    serverVersion,
    spaVersion,
    updateAvailable,
    noteServerVersion,
    reset,
  };
});
