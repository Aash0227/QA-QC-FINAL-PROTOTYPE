/* vite.config.js — bundles the existing vanilla ES-module app AND the new
   React shell (src/react/, entry react.html) under one build.

   - index.html (vanilla panels) stays the default entry and behavior.
   - react.html builds the React foundation shell served at /react.html —
     the sandbox for the Phase 3+ Pipeline UI migration.
   - Tailwind v4 runs through @tailwindcss/vite and only processes
     src/react/index.css, so the legacy app.css/tokens.css are untouched.
   - "@/*" aliases src/react/* (shadcn convention @/components/ui, @/lib/utils).

   Two deployment shapes, both served by FastAPI on the same origin:
     npm run build  -> frontend/dist/, which config.FRONTEND_DIR picks up.
     npm run dev    -> :5173 with /api proxied to the backend on :8077.
   config.FRONTEND_DIR falls back to this source directory whenever dist/ is
   absent, so a failed or skipped build degrades to the pre-Vite behaviour
   instead of serving nothing. */

import { fileURLToPath, URL } from "node:url";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const BACKEND = "http://127.0.0.1:8077";

export default defineConfig({
  root: ".",
  // Relative asset URLs: the app is always served from the origin root today,
  // but relative paths survive a sub-path mount without a rebuild.
  base: "./",
  plugins: [react(), tailwindcss()],
  resolve: {
    // three ships its addons under examples/jsm; the old importmap did this
    // mapping in the browser, Vite does it at build time.
    alias: {
      "three/addons/": "three/examples/jsm/",
      "@": fileURLToPath(new URL("./src/react", import.meta.url)),
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    // Three.js alone is ~600 kB; the default 500 kB warning is pure noise here.
    chunkSizeWarningLimit: 1200,
    sourcemap: true,
    rollupOptions: {
          input: {
            main: fileURLToPath(new URL("./index.html", import.meta.url)),
            legacy: fileURLToPath(new URL("./legacy.html", import.meta.url)),
          },
        },
  },
  server: {
    port: 5173,
    proxy: {
      // Covers fetch, <img> crops, SSE (/api/pipeline/events) and exports —
      // every backend call in the app is under /api.
      "/api": { target: BACKEND, changeOrigin: true },
    },
  },
});
