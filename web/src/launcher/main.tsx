import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { installPageTheme } from "../lib/pageTheme";
import { installPaper } from "../lib/paper";
import { installPaperImages } from "../lib/paperImg";
import { Launcher } from "./Launcher";
import "./launcher.css";

// `deskdot launcher` loads /launcher?shell=win|mac|gtk inside its own window; plain browsers get no shell
const shell = new URLSearchParams(location.search).get("shell");
document.documentElement.dataset.shell = shell ?? "browser";
// the studio's page theme (launcher.html painted the cached copy first; this follows changes made in the studio)
installPageTheme();
// the studio's light-mode paper panel: the launcher's LED previews follow it (lib/paper.ts, lib/paperImg.ts)
installPaper();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Launcher />
  </StrictMode>,
);
installPaperImages();
