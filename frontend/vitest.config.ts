import { defineConfig, mergeConfig } from 'vitest/config'
import viteConfig from './vite.config'

// Vitest configuration for the SPA unit and cross-module tests.  Merges
// vite.config.ts so the `@/` alias and the Vue plugin are shared with the
// app build.  See docs/spa/testing.md for how to run and write tests.
//
export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      environment: 'happy-dom',
      // client.ts fetches relative URLs (`/api/v1/...`); a page URL gives
      // them an origin to resolve against, the same way the browser does
      // under the Django-served `/app/` shell.
      environmentOptions: { happyDOM: { url: 'http://localhost/app/' } },
      setupFiles: ['tests/setup.ts'],
      include: ['tests/**/*.test.ts'],
      restoreMocks: true,
      // `vi.stubEnv()` values (e.g. a per-test TZ) are undone after each test.
      unstubEnvs: true,
      // A fixed zone and locale make local-time date arithmetic and
      // `toLocaleDateString(undefined, ...)` output the same on any machine.
      // Vitest passes these to the worker process's environment.  A single
      // test switches zones with `vi.stubEnv('TZ', ...)`.
      env: { TZ: 'America/New_York', LC_ALL: 'en_US.UTF-8' },
      coverage: {
        provider: 'v8',
        include: ['src/**'],
        reportsDirectory: 'coverage',
        reporter: ['text-summary', 'text', 'html'],
        thresholds: {
          'src/api/**': { lines: 80 },
          'src/composables/**': { lines: 80 },
          'src/domain/**': { lines: 80 },
          'src/models/**': { lines: 80 },
          'src/stores/**': { lines: 80 },
        },
      },
    },
  }),
)
