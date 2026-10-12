import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'
import { existsSync, readFileSync } from 'node:fs'
import { hostname } from 'node:os'

// The Django dev server is HTTPS, with this host's mkcert certificate from
// deployment/ssl/<DEV_HOSTNAME>-ssl_{crt,key}.pem.  Browsers block mixed
// content, so the Vite dev server serves HTTPS with the same certificate.
// DEV_HOSTNAME comes from the repository's .env (see deployment/README.md).
// Where the certificate does not exist, as in CI, Vite serves plain HTTP.
const repoRoot = fileURLToPath(new URL('..', import.meta.url))
const devHostname =
  loadEnv('development', repoRoot, 'DEV_HOSTNAME').DEV_HOSTNAME ?? hostname()
const sslCert = `${repoRoot}deployment/ssl/${devHostname}-ssl_crt.pem`
const sslKey = `${repoRoot}deployment/ssl/${devHostname}-ssl_key.pem`
const httpsConfig =
  existsSync(sslCert) && existsSync(sslKey)
    ? { cert: readFileSync(sslCert), key: readFileSync(sslKey) }
    : undefined

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],

  resolve: {
    alias: {
      // Allows @/stores/auth instead of ../../stores/auth throughout src/
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },

  // django-vite joins STATIC_URL (/static/) into the dev-server asset URLs
  // (e.g. https://localhost:5173/static/@vite/client), so Vite must serve
  // from /static/ in both dev and production.
  base: '/static/',

  build: {
    // manifest.json is required by django-vite to resolve hashed asset filenames.
    manifest: true,
    outDir: 'dist',
    rollupOptions: {
      // Explicit entry so the manifest always records it under a stable key.
      input: '/src/main.ts',
    },
  },

  server: {
    port: 5173,
    // Fail fast if port is taken rather than silently switching ports, so
    // Django's DJANGO_VITE dev_server_port setting stays in sync.
    strictPort: true,
    // Allow the Django dev server (different origin) to load assets.
    cors: true,
    // Make asset URLs (fonts, images) in CSS point back to Vite's origin,
    // not the page origin (Django). Without this, url() in @font-face
    // resolves to localhost:8000/static/ instead of localhost:5173/static/.
    origin: `http${httpsConfig ? 's' : ''}://localhost:5173`,
    https: httpsConfig,
  },
})
