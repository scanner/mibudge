import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],

  resolve: {
    alias: {
      // Allows @/stores/auth instead of ../../stores/auth throughout src/
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },

  // In production Django serves static files from /static/.
  // In dev, django-vite points script tags directly at the Vite dev server,
  // so the base value is not used.
  base: process.env.NODE_ENV === 'production' ? '/static/' : '/',

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
  },
})
