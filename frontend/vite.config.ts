import { defineConfig } from 'vite';
import angular from '@analogjs/vite-plugin-angular';
import { resolve } from 'path';

const BACKEND = 'http://localhost:8000';

// All URL prefixes served by the Orchestrator FastAPI app.
// These are exact API path prefixes — the dev server forwards them to FastAPI.
// Angular SPA routes (/encounters, /dashboard, /agents/*) are NOT listed here
// so they are always served as index.html by the Vite dev server.
const PROXIED_PREFIXES = [
  '/tool',
  '/encounter', // /encounter/start, /encounter/{id}/confirm, etc.
  '/health',
  '/status',
  '/swarm', // /swarm/stream, /swarm/cycle
  '/intake', // /intake/form, /intake/telegram
  '/api/encounters', // explicit API prefix to avoid clashing with SPA /encounters
  '/chw',
  '/referral',
  '/follow-up',
  '/alert',
  '/protocol',
  '/workflow',
  '/agent', // /agent/* ADK routes
];

const proxyEntries = Object.fromEntries(
  PROXIED_PREFIXES.map((prefix) => [
    prefix,
    { target: BACKEND, changeOrigin: true },
  ]),
);

export default defineConfig({
  root: '.',
  plugins: [angular()],

  resolve: {
    alias: {
      '@shared': resolve(__dirname, 'src/shared'),
    },
  },

  build: {
    outDir: 'dist',
    emptyOutDir: true,
    target: 'es2022',
  },

  define: {
    // Injected at build time; overridden by VITE_API_URL in CI/CD
    'import.meta.env.VITE_API_URL': JSON.stringify(
      process.env.VITE_API_URL || 'http://localhost:8000',
    ),
  },

  server: {
    port: 5173,
    proxy: proxyEntries,
  },
});
