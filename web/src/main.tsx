import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { installDeepLinks } from "./lib/deeplink";
import "./index.css";

// The studio was rebuilt while this page was open: its lazy chunks (e.g. the 3D code) have new names, so the old
// ones 404. Reload once to pick up the new build instead of failing (guarded so it can never loop).
window.addEventListener("vite:preloadError", (e) => {
  try {
    const last = Number(sessionStorage.getItem("deskdot.reloadedAt") ?? 0);
    if (Date.now() - last > 30_000) {
      sessionStorage.setItem("deskdot.reloadedAt", String(Date.now()));
      e.preventDefault();
      location.reload();
    }
  } catch {
    /* private mode: let the caller show its error */
  }
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
installDeepLinks();
