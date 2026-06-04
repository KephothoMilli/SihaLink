import { defineConfig } from "vite";
import angular from "@analogjs/vite-plugin-angular";
import { resolve } from "path";

const BACKEND = "http://localhost:8000";

// All URL prefixes served by the Orchestrator FastAPI app
const PROXIED_PREFIXES = ["/tool", "/encounter", "/health"];

const proxyEntries = Object.fromEntries(
  PROXIED_PREFIXES.map((prefix) => [
    prefix,
    { target: BACKEND, changeOrigin: true },
  ]),
);

export default defineConfig({
  root: ".",
  plugins: [angular()],

  resolve: {
    alias: {
      "@shared": resolve(__dirname, "src/shared"),
    },
  },

  build: {
    outDir: "dist",
    emptyOutDir: true,
    target: "es2022",
  },

  define: {
    // Injected at build time; overridden by VITE_API_URL in CI/CD
    "import.meta.env.VITE_API_URL": JSON.stringify(
      process.env.VITE_API_URL || "http://localhost:8000",
    ),
  },

  server: {
    port: 5173,
    proxy: proxyEntries,
  },
});
