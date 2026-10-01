import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// `npm run dev` proxies the API and WebSocket to the engine on :8765.
const ENGINE = process.env.DOTDECK_URL ?? "http://127.0.0.1:8765";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      "/api": ENGINE,
      "/ws": { target: ENGINE.replace(/^http/, "ws"), ws: true },
    },
  },
  build: { outDir: "dist", sourcemap: true, chunkSizeWarningLimit: 1500 },
});
