import { resolve } from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// `npm run dev` proxies the API and WebSocket to the engine on :8765.
const ENGINE = process.env.DESKDOT_URL ?? "http://127.0.0.1:8765";
// `DESKDOT_WEBAPP=1` builds the studio for the browser web app at idotmatrix.com/app/ (scripts/build_webapp.py):
// base /app/, the studio page only, no source maps. The normal desktop build is unchanged.
const WEBAPP = process.env.DESKDOT_WEBAPP === "1";

export default defineConfig({
  base: WEBAPP ? "/app/" : "/",
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
    sourcemap: !WEBAPP,
    chunkSizeWarningLimit: 1500,
    // two pages: the studio and the system-wide command bar (`deskdot launcher`, served at /launcher)
    rollupOptions: {
      input: WEBAPP
        ? { studio: resolve(import.meta.dirname, "index.html") }
        : {
            studio: resolve(import.meta.dirname, "index.html"),
            launcher: resolve(import.meta.dirname, "launcher.html"),
          },
    },
  },
});
