import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'
import { existsSync, readFileSync } from 'node:fs'
import { hostname } from 'node:os'

// The main Django dev server is served over HTTPS (via the reverse proxy
// using the repo-level mkcert certs in deployment/ssl/).  Browsers block
// mixed content, so the Vite dev server must also be HTTPS -- reuse the
// same mkcert cert/key so the browser's existing trust carries over.
// In CI the certs don't exist, so fall back to plain HTTP for the dev server.
// Cert files are prefixed with the hostname so multiple machines sharing a
// filesystem each maintain independent certs.  Falls back to unprefixed names
// for prod or simple single-host setups.
const host = hostname()
const sslDir = fileURLToPath(new URL('../deployment/ssl', import.meta.url))
const resolveSslPath = (stem: string) => {
  const prefixed = `${sslDir}/${host}-${stem}`
  return existsSync(prefixed) ? prefixed : `${sslDir}/${stem}`
}
const sslCert = resolveSslPath('ssl_crt.pem')
const sslKey = resolveSslPath('ssl_key.pem')
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
