import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { Launcher } from "./Launcher";
import "./launcher.css";

// `deskdot launcher` loads /launcher?shell=win|mac|gtk inside its own window; plain browsers get no shell
const shell = new URLSearchParams(location.search).get("shell");
document.documentElement.dataset.shell = shell ?? "browser";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Launcher />
  </StrictMode>,
);
