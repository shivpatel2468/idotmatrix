import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { installDeepLinks } from "./lib/deeplink";
import { installStudioSounds } from "./lib/studioSound";
import { installPageTheme, syncPageTheme } from "./lib/pageTheme";
import { useStore } from "./lib/store";
import { installTheme } from "./lib/theme";
import { installPaper } from "./lib/paper";
import { installPaperImages } from "./lib/paperImg";
import { installGlass } from "./lib/glass";
import "./index.css";

// the page theme (index.html painted the cached copy before first paint; this re-derives it and keeps it live),
// then light / dark / auto (likewise)
installPageTheme();
installTheme();
// light mode's paper panel (html[data-panel]; lib/paper.ts) — follows the theme from here on
installPaper();
// Liquid Glass: clear, frosted or solid for this device (html[data-glass]), the edge lens and the specular highlight
installGlass();
// the engine owns the page theme: every device follows its pick (docs/STUDIO_UI.md § Page themes)
useStore.subscribe((s) => syncPageTheme(s.state?.settings?.page_theme));

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
installStudioSounds();
installPaperImages(); // preview <img>s drawn through the paper mapping while it is on
