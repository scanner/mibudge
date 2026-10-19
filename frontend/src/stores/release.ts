//
// Release store: the release the server runs, as its responses report
// it.  Store layer.
//
// `createSessionHttpClient()` passes every response's
// `X-Mibudge-Version` to `noteServerVersion()`.  `unsupportedServer`
// is true once the server reports a release outside the range this
// bundle supports (`domain/release.ts`); the shell then offers a
// reload.
//

// 3rd party imports
//
import { defineStore } from "pinia";
import { computed, ref } from "vue";

// app imports
//
import {
  isUnsupportedServer,
  SPA_VERSION,
  SUPPORTED_SERVER,
} from "@/domain/release";

////////////////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////
//
export const useReleaseStore = defineStore("release", () => {
  const serverVersion = ref<string | null>(null);
  const spaVersion = SPA_VERSION;
  const supportedServer = SUPPORTED_SERVER;

  const unsupportedServer = computed(() =>
    isUnsupportedServer(serverVersion.value, supportedServer),
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
    supportedServer,
    unsupportedServer,
    noteServerVersion,
    reset,
  };
});
