import { resolve } from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// `npm run dev` proxies the API and WebSocket to the engine on :8765.
const ENGINE = process.env.DESKDOT_URL ?? "http://127.0.0.1:8765";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      "/api": ENGINE,
      "/ws": { target: ENGINE.replace(/^http/, "ws"), ws: true },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
    chunkSizeWarningLimit: 1500,
    // two pages: the studio and the system-wide command bar (`deskdot launcher`, served at /launcher)
    rollupOptions: {
      input: {
        studio: resolve(import.meta.dirname, "index.html"),
        launcher: resolve(import.meta.dirname, "launcher.html"),
      },
    },
  },
});
